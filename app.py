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
from src.tools.impl.corpus import Corpus
from src.tools.registry import REGISTRY
from src.ui.theme import CSS, HERO_SVG, LOGO, badge, matrix_html, steps_html

E = html.escape
st.set_page_config(page_title="MarketMind AI", page_icon="🧠", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)
ss = st.session_state
ss.setdefault("pipe", None)
ss.setdefault("events", [])
ss.setdefault("naive", None)

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
st.markdown(f"""<div class="mm-hero"><div>
<h1>MarketMind AI</h1>
<p>An autonomous business-research agent whose every claim can be checked: decomposed into a plan, gathered by tools,
typed as fact or inference, audited by a quality checker, and published only when a named person approves.</p>
<div class="tags"><span class="mm-tag">🔧 Hand-built agent loop</span><span class="mm-tag">📐 Strict schemas</span>
<span class="mm-tag">🧾 Evidence-bound claims</span><span class="mm-tag">🛡️ Injection-aware</span><span class="mm-tag">🧑‍⚖️ Human approval gate</span></div>
</div>{HERO_SVG}</div>""", unsafe_allow_html=True)
st.markdown(steps_html(state.stage if state else "created"), unsafe_allow_html=True)

if state:
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Run", state.run_id[-6:])
    m2.metric("Evidence", len(state.evidence))
    m3.metric("Tool calls", f"{state.tool_calls}/{pipe.settings.max_tool_calls}")
    m4.metric("Iterations", f"{state.iteration}/{pipe.settings.max_iterations}")
    m5.metric("Spend", f"${pipe.usage.total_cost:.4f}", f"of ${pipe.settings.budget_usd:.2f}", delta_color="off")


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
    try:
        return fn()
    except (ConfigError, InputError, ApprovalError, PipelineError) as e:
        st.error(f"⚠️ {e}")
    except LLMError as e:
        hints = {"auth": "Check the key in the sidebar.", "quota": "Check billing or the key's spend limit.",
                 "rate_limit": "Wait a minute and retry.", "context_length": "Lower steps per sub-question.",
                 "budget": "Raise the cost ceiling or start a new run."}
        st.error(f"🛑 API {e.kind}: {e.message} {hints.get(e.kind, '')}")
    finally:
        if ss.pipe:
            ss.pipe.save()


tabs = st.tabs(["🧭 Brief", "🗺️ Plan", "🔬 Research", "🧾 Evidence", "🧪 Quality", "✅ Approval", "📄 Report",
                "💸 Usage", "🛡️ Tool lab", "🗂️ Runs"])

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
        if st.button("🧭 Analyse request", type="primary", disabled=not api_key):
            def go():
                ss.pipe = Pipeline(build_settings())
                ss.events = []
                with st.spinner("Interrogating the request for ambiguity…"):
                    ss.pipe.analyse(request)
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
        types = st.multiselect("Claim types", ["fact", "inference", "recommendation", "uncertainty"],
                               ["fact", "inference", "recommendation", "uncertainty"])
        for e in state.evidence.values():
            if e.claim_type.value not in types:
                continue
            src = e.source_detail.get("title") or e.source_detail.get("operation") or e.source_ref
            extra = (f" · corroborated by {', '.join(e.corroboration)}" if e.corroboration else "") + \
                    (f" · ⚠️ conflicts with {', '.join(e.conflicts_with)}" if e.conflicts_with else "")
            st.markdown(f'<div class="ev-line">{badge(e.claim_type.value)}<b>{e.evidence_id}</b> · {E(e.claim)}<br>'
                        f'<span class="mm-muted">📄 {E(str(src))} ({e.source_ref}) · credibility {e.credibility.value} · '
                        f'confidence {e.confidence.value} · {E(e.recency)} · for {e.question_id}{E(extra)}</span>'
                        + (f'<br><span class="mm-muted">“{E(e.quote[:220])}”</span>' if e.quote else "") + "</div>", unsafe_allow_html=True)
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
        st.subheader("Cost by stage")
        st.bar_chart(df["cost_usd"], color="#8B6CFF")
        st.dataframe(df, width="stretch")
        if u["unpriced_models"]:
            st.warning(f"Unknown pricing for {u['unpriced_models']} — a pessimistic fallback price was used.")
        with st.expander("Every call"):
            st.dataframe(pd.DataFrame(pipe.usage.to_list()), hide_index=True, width="stretch")

# ============================================================== 9 tool lab
with tabs[8]:
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

# ============================================================== 10 runs
with tabs[9]:
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
        st.caption(f"Artefacts in `{p}`: " + ", ".join(sorted(x.name for x in p.iterdir())))

st.markdown('<p class="mm-muted" style="text-align:center;margin-top:2rem">MarketMind AI · AAI-412 / PRAC-05 · '
            'Every claim typed, sourced and human-approved.</p>', unsafe_allow_html=True)
