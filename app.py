"""MarketMind AI — Streamlit console.   Run:  streamlit run app.py

The API key is entered in the sidebar and kept only in this browser session's memory.
It is never written to disk, logs, run artefacts or screenshots (logs are scrubbed).
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.agents.planner import naive_plan
from src.agents.report_generator import render_markdown
from src.agents.request_analyser import InputError
from src.approval.gate import DECISIONS, SCOPE_FIELDS, ApprovalError, decide, reviewer_brief
from src.config import DEFAULT_MODELS, DEFAULT_TEMPERATURES, STAGES, ConfigError, Settings, mask_key
from src.llm.client import LLMError, smoke_test
from src.pipeline import Pipeline, PipelineError
from src.scenarios import SCENARIOS
from src.schemas.plan import validate_plan
from src.state.persistence import list_runs, load_state
from src.state.research_state import ResearchState
from src.tools.dispatcher import Dispatcher
from src.tools.impl.base import ToolContext
from src.tools.impl.corpus import Corpus, scan_injection
from src.tools.registry import REGISTRY
import re

from src.ui.theme import (CSS, EPISTEMIC, ICON_PATH, LOGO, badge, hero_html, matrix_html, progress_pct, stats_html,
                          steps_html)

E = html.escape
st.set_page_config(page_title="MarketMind AI", page_icon=str(ICON_PATH) if ICON_PATH.exists() else "🤖",
                   layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)
ss = st.session_state
ss.setdefault("pipe", None)
ss.setdefault("events", [])
ss.setdefault("naive", None)
ss.setdefault("flash", [])  # messages that must survive the st.rerun() that follows an action


@st.cache_resource(show_spinner=False)
def browse_corpus() -> Corpus:
    _s = Settings.from_env(require_key=False)
    return Corpus(_s.corpus_dir, _s.corpus_reference_date)

# ============================================================== sidebar
with st.sidebar:
    st.markdown(LOGO, unsafe_allow_html=True)
    api_key = st.text_input("🔑 OpenAI API key", type="password", placeholder="sk-…",
                            help="Kept in this session's memory only. Use a project key with a spend limit.")
    c1, c2 = st.columns(2)
    test_conn = c1.button("Test key", width="stretch")
    if c2.button("New run", width="stretch"):
        ss.pipe, ss.events, ss.naive = None, [], None
        st.rerun()
    if api_key:
        st.caption(f"Key loaded: `{mask_key(api_key)}`")

    with st.expander("🤖 Models per stage", expanded=False):
        st.caption("Verify identifiers against the current OpenAI model list.")
        models = {s: st.text_input(s.replace("_", " "), DEFAULT_MODELS[s], key=f"m_{s}") for s in STAGES}
    with st.expander("🌡️ Temperatures", expanded=False):
        temps = {s: st.slider(s.replace("_", " "), 0.0, 1.0, float(DEFAULT_TEMPERATURES[s]), 0.05, key=f"t_{s}") for s in STAGES}
    with st.expander("🧱 Loop bounds & budget", expanded=True):
        max_iter = st.number_input("Max iterations", 1, 200, 40)
        max_tools = st.number_input("Max tool calls", 1, 300, 60)
        steps_q = st.number_input("Steps per sub-question", 1, 15, 6)
        repairs = st.number_input("Max QC repair rounds", 0, 5, 2)
        budget = st.number_input("Cost ceiling (USD)", 0.001, 50.0, 1.50, 0.05, format="%.3f")
    with st.expander("🧨 Fault injection (tests)", expanded=False):
        fault = st.radio("search_information", ["none", "fail first 2 calls", "always fail", "timeout"], index=0)
    reviewer = st.text_input("🧑‍⚖️ Reviewer name", placeholder="e.g. Dana Okafor",
                             help="Recorded as the approver identity on every decision.")
    if ss.pipe:
        _st = ss.pipe.state
        st.download_button("📦 Export run (JSON)", _st.model_dump_json(indent=2), f"{_st.run_id}_state.json",
                           "application/json", width="stretch", help="Full run state: scope, plan, evidence, QC, report, audit trail.")
    st.caption("🔒 Your key never leaves this session's memory.")


def build_settings() -> Settings:
    fi = {"none": {}, "fail first 2 calls": {"search_information": "error_first:2"},
          "always fail": {"search_information": "error"}, "timeout": {"search_information": "timeout"}}[fault]
    return Settings.from_env(require_key=True, api_key=api_key or None, models=dict(models), temperatures=dict(temps),
                             max_iterations=int(max_iter), max_tool_calls=int(max_tools),
                             max_steps_per_question=int(steps_q), max_repair_rounds=int(repairs),
                             budget_usd=float(budget), fault_injection=fi)


if test_conn:
    try:
        with st.sidebar.status("Calling the API…"):
            res = smoke_test(build_settings())
        st.sidebar.success(f"Connected · {res['model']} · {res['tokens']} tokens · ${res['cost_usd']:.6f}")
    except (ConfigError, LLMError) as e:
        st.sidebar.error(str(e))

# ============================================================== hero
pipe: Pipeline | None = ss.pipe
state: ResearchState | None = pipe.state if pipe else None
stage_now = state.stage if state else "created"
st.markdown(hero_html(stage_now), unsafe_allow_html=True)
st.markdown(steps_html(stage_now), unsafe_allow_html=True)

if state:
    st.markdown(stats_html([
        ("🆔 Run", state.run_id[-6:], "", "#FF5E7E"),
        ("🧾 Evidence", str(len(state.evidence)), "", "#FF9F43"),
        ("🔧 Tool calls", str(state.tool_calls), f"/ {pipe.settings.max_tool_calls}", "#FFD93D"),
        ("🔁 Iterations", str(state.iteration), f"/ {pipe.settings.max_iterations}", "#3DDC97"),
        ("💸 Spend", f"${pipe.usage.total_cost:.4f}", f"/ ${pipe.settings.budget_usd:.2f}", "#2EC5FF"),
        ("📍 Progress", f"{progress_pct(stage_now)}%", stage_now.replace("_", " "), "#8B6CFF"),
    ]), unsafe_allow_html=True)

# Errors raised during an action are kept in session state so the rerun that follows doesn't erase them.
for _kind, _msg in ss.flash:
    (st.error if _kind == "error" else st.success)(_msg)
ss.flash = []


def live(label: str):
    """Context manager that streams run-log events into a status box."""
    box = st.status(label, expanded=True)
    icon = {"tool_call": "🔧", "question_status": "📌", "conflict_detected": "⚖️", "injection_flagged": "🛡️",
            "stuck_loop_detected": "🔁", "llm_retry": "⏳", "evidence_rejected": "🗑️", "loop_end": "🏁",
            "repair_round": "🛠️", "qc": "🧪", "permission_blocked": "⛔", "superseded": "🕰️", "answered_from_state": "♻️"}

    def on(ev):
        k = ev["kind"]
        if k not in icon:
            return
        if k == "tool_call":
            txt = f"{ev['tool']} {'✓' if ev['ok'] else '✗ ' + (ev.get('error') or {}).get('code', '')}  `{json.dumps(ev.get('arguments'))[:110]}`"
        elif k == "question_status":
            txt = f"{ev['question_id']} → **{ev['status']}** — {ev['reason'][:110]}"
        else:
            txt = json.dumps({x: y for x, y in ev.items() if x not in ('ts', 'run_id', 'stage', 'kind', 'level')})[:180]
        box.write(f"{icon[k]} {txt}")
    pipe.log.on_event = on
    return box


def guard(fn):
    """Run an action; turn known failures into a message that survives the following st.rerun()."""
    msg = None
    try:
        return fn()
    except (ConfigError, InputError, ApprovalError, PipelineError) as e:
        msg = f"⚠️ {e}"
    except LLMError as e:
        hints = {"auth": "Check the key in the sidebar.", "quota": "Check billing or the key's spend limit.",
                 "rate_limit": "Wait a minute and retry.", "context_length": "Lower steps per sub-question.",
                 "budget": "Raise the cost ceiling or start a new run."}
        msg = f"🛑 API {e.kind}: {e.message} {hints.get(e.kind, '')}"
    finally:
        if msg:
            st.error(msg)
            ss.flash.append(("error", msg))
        if ss.pipe:
            ss.pipe.save()


tabs = st.tabs(["🧭 Brief", "🗺️ Plan", "🔬 Research", "🧾 Evidence", "🧪 Quality", "✅ Approval", "📄 Report",
                "💸 Usage", "📚 Corpus", "🛡️ Tool lab", "🗂️ Runs", "ℹ️ How it works"])

# ============================================================== 1 brief
with tabs[0]:
    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Client request")
        sc = st.selectbox("Scenario", list(SCENARIOS), format_func=lambda k: f"{SCENARIOS[k]['emoji']} {k} · {SCENARIOS[k]['name']}")
        if not SCENARIOS[sc]["corpus"]:
            st.warning("The bundled corpus covers S1 only. Other scenarios will plan correctly but research will mostly "
                       "return 'could not establish' — which is the honest result. Add documents to data/corpus to research them.")
        request = st.text_area("Request as received", SCENARIOS[sc]["request"], height=110, max_chars=2000)
        if st.button("🧭 Analyse request", type="primary", disabled=not api_key or not request.strip()):
            def go():
                new = Pipeline(build_settings())
                with st.spinner("🤖 Interrogating the request for ambiguity…"):
                    new.analyse(request)
                ss.pipe, ss.events, ss.naive = new, [], None  # only adopt the run once analysis succeeded
            guard(go)
            st.rerun()
        if not api_key:
            st.info("🔑 Enter your OpenAI API key in the sidebar to start.")
    with right:
        st.subheader("Normalised scope")
        if state and state.scope:
            s = state.scope
            st.markdown('<div class="mm-card"><div class="mm-kv">' + "".join(
                f"<div><small>{k.replace('_', ' ')}</small><span>{E(str(getattr(s, k)))}</span></div>"
                for k in ["entity_type", "segment", "geography", "time_horizon", "deliverable_type"]) +
                f"<div><small>complexity</small><span>{s.complexity.value}</span></div></div>"
                f"<p style='margin:.8rem 0 0'><b>Objective:</b> {E(s.normalised_objective)}</p></div>", unsafe_allow_html=True)
            if s.injection_suspected:
                st.markdown('<div class="verdict v-warn">🛡️ Instruction-like text detected in the request. It is treated as data — '
                            'evidence rules and the approval gate cannot be switched off.</div>', unsafe_allow_html=True)
        else:
            st.caption("Run the analyser to see the scope.")
    if state and state.scope:
        st.subheader("Ambiguities")
        answers = {}
        for a in state.scope.ambiguities:
            tag = badge("high" if a.resolution.value == "clarify" else "low", "❓ ask client" if a.resolution.value == "clarify" else "📝 assume")
            st.markdown(f'<div class="mm-card">{tag}<b>{E(a.dimension)}</b> — {E(a.issue)}<br>'
                        f'<span class="mm-muted">Default if unanswered: {E(a.default_assumption)}</span></div>', unsafe_allow_html=True)
            if a.resolution.value == "clarify":
                answers[a.dimension] = st.text_input(f"Answer: {a.clarification_question}", key=f"clar_{a.dimension}")
        if not state.scope.ambiguities:
            st.caption("No ambiguity found.")
        if st.button("🗺️ Build research plan", type="primary", disabled=state.plan is not None and state.stage != "planner"):
            def go():
                with st.spinner("Decomposing into answerable sub-questions…"):
                    pipe.plan(answers)
            guard(go)
            st.rerun()

# ============================================================== 2 plan
with tabs[1]:
    if not (state and state.plan):
        st.info("No plan yet. Analyse a request in 🧭 Brief.")
    else:
        probs = validate_plan(state.plan, state.scope)
        st.markdown(f'<div class="verdict {"v-pass" if not probs else "v-warn"}">'
                    f'{"✅ Plan passes the code validator" if not probs else "⚠️ Validator: " + E("; ".join(probs))} · '
                    f'{len(state.plan.objectives)} objectives · {len(state.all_questions())} sub-questions</div>', unsafe_allow_html=True)
        for o in state.plan.objectives:
            with st.expander(f"🎯 {o.id} · {o.title}", expanded=True):
                st.dataframe(pd.DataFrame([{"id": q.id, "question": q.text, "evidence": q.evidence_type.value,
                                            "tools": ", ".join(t.value for t in q.candidate_tools), "priority": q.priority.value,
                                            "done when": q.done_when,
                                            "status": state.question_status.get(q.id).status if q.id in state.question_status else "open"}
                                           for q in o.sub_questions]), hide_index=True, width="stretch")
        if state.extra_questions:
            st.markdown("**➕ Repair & reviewer questions**")
            st.dataframe(pd.DataFrame([{"id": q.id, "question": q.text, "origin": state.question_status[q.id].origin,
                                        "status": state.question_status[q.id].status} for q in state.extra_questions]),
                         hide_index=True, width="stretch")
        with st.expander("🆚 Compare with a naive single-prompt baseline"):
            if st.button("Generate naive baseline"):
                guard(lambda: ss.__setitem__("naive", naive_plan(pipe.client, state.request)))
            if ss.naive:
                st.markdown(ss.naive)
                st.caption("Typical deficiencies: no ids or stopping conditions, no evidence types or tools, no ambiguity "
                           "handling, unbounded questions such as 'analyse the competitive landscape'.")

# ============================================================== 3 research
with tabs[2]:
    if not (state and state.plan):
        st.info("Build a plan first.")
    else:
        c1, c2 = st.columns(2)
        if c1.button("🔬 Run research loop", type="primary", disabled=state.stage not in ("planner",)):
            def go():
                with live("Agent loop running — tools, evidence, decisions…") as box:
                    reason = pipe.research()
                    box.update(label=f"Loop finished: {reason.replace('_', ' ')}", state="complete")
            guard(go)
            st.rerun()
        if c2.button("🧠 Compare · synthesise · check · draft", type="primary", disabled=state.stage != "researcher"):
            def go():
                with live("Comparison → synthesis → QC (with bounded repair) → report") as box:
                    pipe.analyse_and_report()
                    box.update(label="Draft ready — awaiting human approval", state="complete")
            guard(go)
            st.rerun()
        if state.termination_reasons:
            st.markdown(f'<div class="verdict v-warn">🧱 Termination: {E(", ".join(state.termination_reasons))}</div>', unsafe_allow_html=True)
        rows = []
        for q in state.all_questions():
            qs = state.question_status.get(q.id)
            rows.append({"id": q.id, "question": q.text, "status": qs.status if qs else "open", "steps": qs.steps_used if qs else 0,
                         "evidence": len(state.evidence_for(q.id)), "reason": qs.reason if qs else ""})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"status": st.column_config.TextColumn("status", help="open / answered / unanswerable")})
        if state.tool_history:
            st.subheader("🔧 Tool log")
            st.dataframe(pd.DataFrame([{"id": h["result_id"], "stage": h["stage"], "tool": h["tool"], "ok": "✅" if h["ok"] else "❌",
                                        "arguments": json.dumps(h["arguments"], default=str)[:140],
                                        "error": (h.get("error") or {}).get("code", ""), "latency s": h["latency_s"],
                                        "⚠️ injection": "yes" if h["injection_flags"] else ""} for h in state.tool_history]),
                         hide_index=True, width="stretch", height=320)

# ============================================================== 4 evidence
with tabs[3]:
    if not (state and state.evidence):
        st.info("Evidence appears here as the research loop runs.")
    else:
        allev = list(state.evidence.values())
        counts = {k: sum(1 for e in allev if e.claim_type.value == k) for k in EPISTEMIC}
        dot = {"fact": "🟢", "inference": "🟣", "recommendation": "🔵", "uncertainty": "🟡"}
        st.markdown(stats_html([(f"{dot[k]} {k}", str(v), f"{v / max(1, len(allev)) * 100:.0f}%", EPISTEMIC[k])
                                for k, v in counts.items()]), unsafe_allow_html=True)
        f1, f2, f3 = st.columns([2, 1.4, 1])
        types = f1.multiselect("Claim types", list(EPISTEMIC), list(EPISTEMIC))
        needle = f2.text_input("🔎 Search claims", placeholder="vendor, price, Q1.2…")
        f3.download_button("⬇️ Evidence CSV", pd.DataFrame([{
            "evidence_id": e.evidence_id, "question_id": e.question_id, "claim_type": e.claim_type.value, "claim": e.claim,
            "source_ref": e.source_ref, "credibility": e.credibility.value, "confidence": e.confidence.value,
            "recency": e.recency, "corroboration": ";".join(e.corroboration), "conflicts_with": ";".join(e.conflicts_with),
            "quote": e.quote} for e in allev]).to_csv(index=False), f"{state.run_id}_evidence.csv", "text/csv", width="stretch")
        shown = 0
        for e in allev:
            if e.claim_type.value not in types:
                continue
            if needle and needle.lower() not in f"{e.evidence_id} {e.question_id} {e.claim} {e.quote}".lower():
                continue
            shown += 1
            src = e.source_detail.get("title") or e.source_detail.get("operation") or e.source_ref
            extra = (f" · corroborated by {', '.join(e.corroboration)}" if e.corroboration else "") + \
                    (f" · ⚠️ conflicts with {', '.join(e.conflicts_with)}" if e.conflicts_with else "")
            st.markdown(f'<div class="ev-line" style="--c:{EPISTEMIC.get(e.claim_type.value, "#2C2860")}">'
                        f'{badge(e.claim_type.value)}<span class="mm-id">{e.evidence_id}</span> · {E(e.claim)}<br>'
                        f'<span class="mm-muted">📄 {E(str(src))} ({e.source_ref}) · credibility {e.credibility.value} · '
                        f'confidence {e.confidence.value} · {E(e.recency)} · for {e.question_id}{E(extra)}</span>'
                        + (f'<br><span class="mm-muted">“{E(e.quote[:220])}”</span>' if e.quote else "") + "</div>", unsafe_allow_html=True)
        if not shown:
            st.caption("No evidence matches these filters.")
        st.subheader("🏁 Comparison matrix")
        st.markdown(matrix_html(state.matrix or {}), unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader(f"🗑️ Rejection log ({len(state.rejections)})")
            if state.rejections:
                st.dataframe(pd.DataFrame(state.rejections), hide_index=True, width="stretch", height=260)
        with c2:
            st.subheader(f"🛡️ Security flags ({len(state.flags)})")
            for f in state.flags:
                st.markdown(f'<div class="ev-line">{E(json.dumps(f)[:300])}</div>', unsafe_allow_html=True)

# ============================================================== 5 quality
with tabs[4]:
    if not (state and state.qc):
        st.info("Quality control runs after synthesis.")
    else:
        qc = state.qc
        st.markdown(f'<div class="verdict {"v-pass" if qc["verdict"] == "pass" else "v-fail"}">'
                    f'{"✅ PASS" if qc["verdict"] == "pass" else "❌ FAIL"} · repair rounds used: {state.repair_round}/{pipe.settings.max_repair_rounds}</div>',
                    unsafe_allow_html=True)
        cols = st.columns(5)
        for c, (k, v) in zip(cols, qc["counts"].items()):
            c.metric(k.replace("_", " "), v)
        st.dataframe(pd.DataFrame([{"id": d["id"], "type": d["type"], "severity": d["severity"], "location": d["location"],
                                    "detail": d["detail"], "gap question": d.get("gap_question") or "", "by": d["detected_by"]}
                                   for d in qc["defects"]]), hide_index=True, width="stretch")
        inv = (state.report or {}).get("qc", {}).get("invariant_violations", [])
        if inv:
            st.warning("Cross-field invariant violations: " + "; ".join(inv[:8]))

# ============================================================== 6 approval
with tabs[5]:
    if not (state and state.report):
        st.info("The approval gate opens once a draft report exists.")
    else:
        b = reviewer_brief(state)
        st.subheader("Reviewer brief")
        st.caption("Everything you need to decide is above the draft. Absence of a decision is not approval.")
        conf = b["confidence"] or {}
        cls = {"high": "v-pass", "medium": "v-warn", "low": "v-fail"}.get(conf.get("level"), "v-warn")
        st.markdown(f'<div class="verdict {cls}">Overall confidence: {E(str(conf.get("level", "?")).upper())} · QC {E(str(b["qc_verdict"]))} · '
                    f'report {E(str(b["report_status"]))}</div><div class="mm-card"><b>🎯 Objective</b><br>{E(b["objective"] or "")}'
                    f'<br><span class="mm-muted">{E(conf.get("rationale", ""))}</span><br><br>'
                    + "".join(badge(k, f"{k}: {v}") for k, v in b["claims_by_type"].items()) + "</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**📝 Recorded assumptions**")
            for a in b["assumptions"] or ["none"]:
                st.markdown(f"- {a}")
            st.markdown(f"**🧪 Outstanding defects ({len(b['outstanding_defects'])})**")
            for d in b["outstanding_defects"][:10]:
                st.markdown(f"- `{d['severity']}` {d['type']}: {d['detail'][:140]}")
        with c2:
            st.markdown("**🕳️ Limitations & gaps**")
            for l in b["limitations"][:14]:
                st.markdown(f"- {l}")
        with st.expander("📄 Read the full draft"):
            st.markdown(render_markdown(state.report), unsafe_allow_html=True)
        st.divider()
        if state.status in ("approved", "rejected"):
            st.success(f"Decision recorded: **{state.status}**.") if state.status == "approved" else st.error("Run rejected and archived. Nothing was published.")
        else:
            st.subheader("Your decision")
            labels = {"approve": "✅ Approve & publish", "reject": "⛔ Reject", "expand": "➕ Request additional research",
                      "rescope": "🔁 Modify scope"}
            dec = st.radio("Decision", DECISIONS, index=None, format_func=labels.get, horizontal=True)
            notes = st.text_area("Notes / reason", height=80)
            qs, changes, ok = None, None, True
            if dec == "expand":
                qs = [q for q in st.text_area("Specific questions (one per line, max 5)").splitlines() if q.strip()]
            if dec == "rescope":
                changes = {f: st.text_input(f"New {f.replace('_', ' ')}", placeholder=str(getattr(state.scope, f))) for f in SCOPE_FIELDS}
                st.caption("Retention rule: evidence that shares ≥2 content terms with a regenerated sub-question (or concerns a "
                           "named entity) is kept and remapped; the rest is archived, never deleted.")
            if dec == "approve":
                ok = st.checkbox("I have reviewed the brief, the defects and the limitations, and I take responsibility for publication.")
            if st.button("Record decision", type="primary", disabled=dec is None or not ok):
                def go():
                    with live(f"Applying decision: {dec}") as box:
                        out = decide(pipe, dec, reviewer, notes, qs, changes)
                        box.update(label=f"Decision applied → {out['status']}", state="complete")
                guard(go)
                st.rerun()
            if not reviewer:
                st.caption("Enter your name in the sidebar — every decision records an approver.")
        if state.approval_history:
            st.markdown("**🧾 Audit trail**")
            st.dataframe(pd.DataFrame(state.approval_history), hide_index=True, width="stretch")

# ============================================================== 7 report
with tabs[6]:
    if not (state and state.report):
        st.info("No report yet.")
    else:
        if state.status == "approved":
            st.markdown('<div class="verdict v-pass">✅ Published — approved by ' + E(state.report["approval"]["approver"]) + "</div>", unsafe_allow_html=True)
        else:
            st.markdown('<div class="verdict v-warn">📝 Draft — not publishable until a named reviewer approves it.</div>', unsafe_allow_html=True)
        md = render_markdown(state.report)
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ Report (Markdown)", md, f"{state.report['report_id']}.md", "text/markdown", width="stretch")
        c2.download_button("⬇️ Report (JSON, schema-valid)", json.dumps(state.report, indent=2, default=str),
                           f"{state.report['report_id']}.json", "application/json", width="stretch")
        st.markdown(md, unsafe_allow_html=True)

# ============================================================== 8 usage
with tabs[7]:
    if not pipe or not pipe.usage.records:
        st.info("Usage appears after the first model call.")
    else:
        u = pipe.usage.summary()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total cost", f"${u['total_cost_usd']:.4f}")
        c2.metric("Tokens", f"{u['total_tokens']:,}")
        c3.metric("LLM calls", u["calls"])
        c4.metric("Budget used", f"{min(100, u['total_cost_usd'] / pipe.settings.budget_usd * 100):.0f}%")
        st.progress(min(1.0, u["total_cost_usd"] / pipe.settings.budget_usd))
        df = pd.DataFrame(u["by_stage"]).T
        g1, g2 = st.columns(2)
        with g1:
            st.subheader("💰 Cost by stage")
            st.bar_chart(df["cost_usd"].astype(float), color="#FF5FD2", height=230)
        with g2:
            st.subheader("🔤 Tokens by stage")
            st.bar_chart(df[["prompt_tokens", "completion_tokens"]].astype(int), color=["#2EC5FF", "#FFD93D"],
                         stack=True, height=230)
        st.dataframe(df, width="stretch")
        if u["unpriced_models"]:
            st.warning(f"Unknown pricing for {u['unpriced_models']} — a pessimistic fallback price was used.")
        with st.expander("Every call"):
            st.dataframe(pd.DataFrame(pipe.usage.to_list()), hide_index=True, width="stretch")

# ============================================================== 9 corpus explorer
with tabs[8]:
    st.subheader("📚 Corpus explorer")
    st.caption("Browse and search the documents the agent can retrieve — the same BM25 index its search tool uses. "
               "No API key or cost.")
    corpus = browse_corpus()
    docs = list(corpus.docs.values())
    if not docs:
        st.info("No documents in data/corpus.")
    else:
        by_type = pd.Series([d.source_type for d in docs]).value_counts()
        palette = ["#FF5E7E", "#FF9F43", "#FFD93D", "#3DDC97", "#2EC5FF", "#8B6CFF", "#FF5FD2"]
        st.markdown(stats_html([("📄 Documents", str(len(docs)), "", "#FF5E7E"),
                                ("🧩 Sections", str(len(corpus.sections)), "", "#FFD93D"),
                                ("🏢 Vendors", str(len({d.vendor for d in docs if d.vendor})), "", "#3DDC97"),
                                ("📅 Reference date", corpus.reference.isoformat(), "", "#2EC5FF")] +
                               [(f"🏷️ {t.replace('_', ' ')}", str(n), "", palette[(i + 4) % 7]) for i, (t, n) in enumerate(by_type.items())]),
                    unsafe_allow_html=True)
        q1, q2, q3 = st.columns([2.2, 1, 1])
        cq = q1.text_input("🔎 Search the corpus", placeholder="e.g. Converso seat minimum, market size 2025")
        ctype = q2.selectbox("Source type", ["any"] + sorted(by_type.index))
        crec = q3.selectbox("Recency", ["any", "1y", "3y", "5y"])
        if cq.strip():
            hits = corpus.search(cq, ctype, 8, crec)
            if not hits:
                st.caption("No matching sections.")
            terms = [t for t in re.findall(r"[A-Za-z0-9$%]{3,}", cq) if t.lower() not in ("amp", "quot")]
            for h in hits:
                snip = E(h["snippet"])
                for t in terms:
                    snip = re.sub(f"({re.escape(E(t))})", r"<mark>\1</mark>", snip, flags=re.I)
                st.markdown(f'<div class="mm-doc"><span class="mm-id">{E(h["document_id"])}</span> · <b>{E(h["title"])}</b> › '
                            f'{E(h["section"])} <span class="badge b-low">score {h["score"]}</span>'
                            f'<span class="badge b-recommendation">{E(h["source_type"])}</span><br>'
                            f'<span class="mm-muted">{snip}</span></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"id": d.id, "title": d.title, "type": d.source_type, "vendor": d.vendor, "date": d.date,
                                    "recency": corpus.recency_bucket(d), "credibility hint": d.credibility_hint,
                                    "⚠️ injection lines": len(scan_injection(d.text))} for d in docs]),
                     hide_index=True, width="stretch", height=260)
        pick = st.selectbox("📖 Read a document", [d.id for d in docs],
                            format_func=lambda i: f"{i} · {corpus.docs[i].title}")
        doc = corpus.get(pick)
        flagged = scan_injection(doc.text)
        if flagged:
            st.markdown('<div class="verdict v-warn">🛡️ This document contains instruction-like text. The agent treats it as '
                        'data and flags it: ' + E(" | ".join(flagged[:3])) + "</div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(doc.text)

# ============================================================== 10 tool lab
with tabs[9]:
    st.subheader("Adversarial dispatcher tests")
    st.caption("Runs against a sandbox state — no API key or cost. Every call must return a structured error, never crash.")
    if "lab" not in ss:
        _s = Settings.from_env(require_key=False)
        ss.lab = Dispatcher(ToolContext(ResearchState(), Corpus(_s.corpus_dir, _s.corpus_reference_date), _s))
    lab: Dispatcher = ss.lab
    presets = {
        "Unknown tool": ("researcher", "send_email", '{"to":"ceo@client.example"}'),
        "Malformed JSON": ("researcher", "search_information", '{"query": "pricing", '),
        "Out-of-enum value": ("researcher", "search_information", '{"query":"pricing","source_type":"blog","max_results":3,"recency_window":"any"}'),
        "Out-of-bounds number": ("researcher", "search_information", '{"query":"pricing","source_type":"any","max_results":500,"recency_window":"any"}'),
        "Path traversal": ("researcher", "retrieve_document", '{"document_id":"../../.env","section":null}'),
        "Code injection": ("researcher", "calculate_metric", '{"operation":"__import__(\'os\')","values":[1],"period":null}'),
        "Write out of stage": ("researcher", "save_research", '{"question_id":"Q1.1","claim":"x costs $1","claim_type":"fact","source_ref":"R0001","confidence":"high","credibility":"high"}'),
        "Valid search": ("researcher", "search_information", '{"query":"Converso Pro seat minimum","source_type":"any","max_results":3,"recency_window":"any"}'),
    }
    cols = st.columns(4)
    for i, (k, (stage, tool, raw)) in enumerate(presets.items()):
        if cols[i % 4].button(k, width="stretch"):
            ss.lab_out = (k, lab.dispatch(stage, tool, raw))
    with st.expander("✍️ Custom call"):
        t = st.selectbox("Tool (or type anything below)", list(REGISTRY) + ["<unknown>"])
        stage = st.selectbox("Calling stage", ["researcher", "evidence_analyst", "comparison", "report_generator"])
        raw = st.text_area("Raw JSON arguments", '{"query":"market size 2025","source_type":"any","max_results":5,"recency_window":"1y"}')
        if st.button("Dispatch"):
            ss.lab_out = ("custom", lab.dispatch(stage, "browse" if t == "<unknown>" else t, raw))
    if ss.get("lab_out"):
        k, env = ss.lab_out
        st.markdown(f'<div class="verdict {"v-pass" if env["ok"] else "v-fail"}">{E(k)}: '
                    f'{"✅ executed" if env["ok"] else "❌ " + E(env["error"]["code"])} — process still running</div>', unsafe_allow_html=True)
        st.json(env, expanded=2)
    st.subheader("Registry & abuse analysis")
    st.dataframe(pd.DataFrame([{"tool": n, "permission": s.permission, "stages": ", ".join(sorted(s.allowed_stages)),
                                "budget": s.budget, "timeout s": s.timeout_s, "abuse if attacker-controlled": s.abuse_case,
                                "prevented by": s.mitigation} for n, s in REGISTRY.items()]), hide_index=True, width="stretch")

# ============================================================== 11 runs
with tabs[10]:
    _s = Settings.from_env(require_key=False)
    runs = list_runs(_s.runs_dir)
    if not runs:
        st.info("No saved runs yet.")
    else:
        st.dataframe(pd.DataFrame(runs), hide_index=True, width="stretch")
        rid = st.selectbox("Open a saved run", [r["run_id"] for r in runs])
        if st.button("📂 Load run", disabled=not api_key):
            def go():
                ss.pipe = Pipeline(build_settings(), state=load_state(_s.runs_dir, rid))
            guard(go)
            st.rerun()
        if not api_key:
            st.caption("Loading a run to continue it requires the API key (for expand / rescope decisions).")
        p = Path(_s.runs_dir) / rid
        if p.is_dir():
            st.caption(f"Artefacts in `{p.name}`: " + ", ".join(sorted(x.name for x in p.iterdir())))

# ============================================================== 12 how it works
with tabs[11]:
    st.subheader("ℹ️ How the agent works")
    flow = [("🧭", "Scope", "Request analyser normalises the brief and lists ambiguities — ask the client or assume.", "#FF5E7E"),
            ("🗺️", "Plan", "Planner decomposes it into sub-questions with evidence types, tools and stop conditions.", "#FF9F43"),
            ("🔬", "Research", "A bounded tool loop searches, retrieves and calculates; every call is validated and logged.", "#FFD93D"),
            ("🏁", "Compare", "Evidence is typed fact / inference / recommendation / uncertainty and placed in a matrix.", "#3DDC97"),
            ("🧠", "Synthesise", "Findings are written only from saved evidence ids — no id, no claim.", "#2EC5FF"),
            ("🧪", "Check", "Quality control finds defects and opens bounded repair rounds.", "#8B6CFF"),
            ("✅", "Approve", "A named human approves, rejects, expands or rescopes. Nothing publishes without it.", "#FF5FD2")]
    st.markdown('<div class="mm-stats" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">' + "".join(
        f'<div class="mm-stat" style="--c:{c}"><small>step {i + 1}</small><b>{ic} {n}</b><br>'
        f'<span class="mm-muted" style="font-size:.78rem">{E(d)}</span></div>' for i, (ic, n, d, c) in enumerate(flow)) + "</div>",
                unsafe_allow_html=True)
    h1, h2 = st.columns(2)
    with h1:
        st.markdown("**🚀 Quick start**\n1. Paste an OpenAI key in the sidebar and press **Test key**.\n"
                    "2. Pick scenario **🎧 S1** (the bundled corpus covers it) → **Analyse request**.\n"
                    "3. Answer any client questions → **Build research plan**.\n"
                    "4. **Run research loop**, then **Compare · synthesise · check · draft**.\n"
                    "5. Review in **✅ Approval**, enter your name, record a decision.")
    with h2:
        st.markdown("**🆓 Try without a key**\n- **📚 Corpus** — search and read every source document.\n"
                    "- **🛡️ Tool lab** — fire adversarial calls at the tool dispatcher.\n\n"
                    "**🎨 Claim colours**\n\n" + " ".join(badge(k) for k in EPISTEMIC), unsafe_allow_html=True)

st.markdown('<p class="mm-foot">🤖 <span>MarketMind AI</span> · AAI-412 / PRAC-05 · '
            'Every claim typed, sourced and human-approved.</p>', unsafe_allow_html=True)
