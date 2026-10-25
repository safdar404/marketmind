"""Report Generator: formats, never researches. Executive summary is written last and checked in code."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.agents.synthesis import SECTIONS, iter_findings
from src.prompts import report_generator as P
from src.schemas.report import ExecutiveSummary, Report
from src.tools.impl.base import ToolError

BADGE = {"fact": "🟢 FACT", "inference": "🟣 INFERENCE", "recommendation": "🔵 RECOMMENDATION", "uncertainty": "🟠 UNCERTAINTY"}


def executive_summary(client, synth: dict, log=None) -> tuple[str, list[dict]]:
    items = [{"id": f["id"], "type": f["claim_type"], "statement": f["statement"]}
             for sec in SECTIONS for f in synth.get(sec, [])]
    issues: list[dict] = []
    if not items:
        return "No findings could be established from the available evidence. See limitations.", issues
    out, defect = client.structured("report_generator", [
        {"role": "system", "content": P.SYSTEM},
        {"role": "user", "content": "Finalised findings (data):\n" + json.dumps(items, indent=1)}],
        ExecutiveSummary, "executive_summary")
    if out is None:
        issues.append({"type": "structured_output_failure", "detail": "executive summary fell back to deterministic list"})
        return "\n".join(f"- {i['statement']} [{i['id']}]" for i in items[:5]), issues
    valid = {i["id"] for i in items}
    lines = []
    for b in out.bullets:  # code check: no claim absent from the body
        refs = [r for r in b.finding_ids if r in valid]
        if not refs:
            issues.append({"type": "summary_unsupported", "detail": f"dropped bullet with no valid finding refs: {b.text[:120]}"})
            continue
        lines.append(f"- {b.text} [{', '.join(refs)}]")
    if log:
        log.event("executive_summary", "report_generator", bullets=len(lines), dropped=len(issues), defect=defect)
    return "\n".join(lines) or "No summary bullet survived validation; see findings.", issues


def overall_confidence(state, qc: dict) -> dict:
    qs = state.all_questions()
    answered = sum(1 for q in qs if state.question_status.get(q.id) and state.question_status[q.id].status == "answered")
    cov = answered / len(qs) if qs else 0
    ev = list(state.evidence.values())
    hi = sum(1 for e in ev if e.credibility.value == "high") / len(ev) if ev else 0
    conflicts = sum(1 for e in ev if e.created_by_stage == "conflict_detector")
    blocking = sum(1 for d in qc.get("defects", []) if d["severity"] == "high")
    level = "high" if cov >= 0.85 and hi >= 0.5 and blocking == 0 and conflicts == 0 else \
            "medium" if cov >= 0.6 and blocking <= 1 else "low"
    return {"level": level, "rationale": (f"Coverage {answered}/{len(qs)} planned questions answered ({cov:.0%}); "
                                          f"{hi:.0%} of {len(ev)} evidence records are high-credibility; "
                                          f"{conflicts} unresolved source conflict(s); {blocking} blocking QC defect(s) outstanding.")}


def limitations(state, qc: dict) -> list[str]:
    out = []
    if state.incomplete_reason:
        out.append(f"INCOMPLETE RUN: {state.incomplete_reason}")
    for q in state.all_questions():
        s = state.question_status.get(q.id)
        if s and s.status == "unanswerable":
            out.append(f"Could not establish ({q.id}): {q.text} — {s.reason}")
        elif s and s.status == "open":
            out.append(f"Not researched ({q.id}): {q.text}")
    m = state.matrix or {}
    for ent, row in m.get("cells", {}).items():
        missing = [a for a, c in row.items() if c["status"] == "NOT_ESTABLISHED"]
        if missing:
            out.append(f"{ent}: not established within the corpus — {', '.join(missing)}")
    for e in state.evidence.values():
        if e.created_by_stage == "conflict_detector":
            out.append(f"Unresolved conflict [{e.evidence_id}]: {e.claim[:260]}")
    for d in qc.get("defects", []):
        if d["severity"] in ("high", "medium") and d["type"] != "contradiction":
            out.append(f"Outstanding QC defect {d['id']} ({d['type']}, {d['severity']}): {d['detail'][:200]}")
    if state.scope:
        for a in state.scope.ambiguities:
            out.append(f"Assumption ({a.dimension}): {a.default_assumption}")
    if not out:
        out.append("No gaps detected: every planned sub-question was answered with corroborated evidence.")
    return out


def assemble(client, state, usage, log=None, sections: list[str] | None = None) -> dict:
    synth = state.synthesis or {}
    qc = state.qc or {"verdict": "not_run", "defects": []}
    if not any(synth.get(s) for s in SECTIONS) and not state.evidence:
        raise ToolError("empty_report", "mandatory sections have no supporting content - nothing to report")
    summary, summary_issues = executive_summary(client, synth, log)
    referenced = {i for _, f in iter_findings(synth) for i in f.get("evidence_ids", [])}
    for r in synth.get("recommendations", []):
        referenced.update(i for i in r.get("motivated_by", []) if i.startswith("E"))
    referenced |= {e.evidence_id for e in state.evidence.values() if e.claim_type.value == "uncertainty"}
    for ent_row in (state.matrix or {}).get("cells", {}).values():
        for c in ent_row.values():
            referenced.update(v["evidence_id"] for v in c["values"])
    appendix = [state.evidence[i] for i in sorted(referenced) if i in state.evidence]
    sources, seen = [], set()
    for e in appendix:
        key = e.source_detail.get("document_id") or e.source_ref
        if key not in seen:
            seen.add(key)
            sources.append({"id": key, "title": e.source_detail.get("title") or e.source_detail.get("operation"),
                            "type": e.source_detail.get("source_type") or e.source_kind.value,
                            "date": e.source_detail.get("date")})
    complete = state.incomplete_reason is None
    report = Report(
        report_id=f"RPT-{state.run_id}", generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        status="complete" if complete else "incomplete", incomplete_reason=state.incomplete_reason,
        model_versions=state.model_versions,
        run_cost={"total_usd": usage.total_cost, "total_tokens": usage.total_tokens, "llm_calls": len(usage.records),
                  "tool_calls": state.tool_calls, "iterations": state.iteration, "elapsed_s": round(state.elapsed_s, 1),
                  "by_stage": usage.by_stage()},
        research_objective={"request": state.request,
                            "objective": state.scope.normalised_objective if state.scope else state.request,
                            "assumptions": [a.default_assumption for a in (state.scope.ambiguities if state.scope else [])],
                            "unresolved_ambiguities": [a.clarification_question for a in (state.scope.ambiguities if state.scope else [])
                                                       if a.resolution.value == "clarify"],
                            "clarifications": state.clarifications,
                            "injection_suspected_in_request": bool(state.scope and state.scope.injection_suspected)},
        executive_summary=summary,
        market_overview=synth.get("market_overview", []), key_trends=synth.get("key_trends", []),
        competitor_analysis={"matrix": state.matrix or {}, "narratives": synth.get("competitor_narratives", [])},
        opportunities=synth.get("opportunities", []), risks=synth.get("risks", []),
        evidence_appendix=appendix, recommendations=synth.get("recommendations", []),
        confidence_level=overall_confidence(state, qc), limitations_and_gaps=limitations(state, qc),
        sources=sources, qc={**qc, "summary_issues": summary_issues}, approval=None,
    )
    data = report.model_dump(mode="json")
    problems = report_invariants(data, state)
    data["qc"]["invariant_violations"] = problems
    state.report = data
    if log:
        log.event("report_draft", "report_generator", status=data["status"], findings=len(list(iter_findings(synth))),
                  appendix=len(appendix), invariant_violations=problems)
    return data


def report_invariants(r: dict, state) -> list[str]:
    """Cross-field invariants no JSON Schema can express (Section 6.3)."""
    probs = []
    appendix = {e["evidence_id"] for e in r["evidence_appendix"]}
    for sec in ["market_overview", "key_trends", "opportunities", "risks", "recommendations"]:
        for f in r[sec]:
            for i in f.get("evidence_ids", []):
                if i not in appendix:
                    probs.append(f"{sec}/{f.get('id')}: evidence id {i} not in appendix")
            if f["claim_type"] == "fact" and not f.get("evidence_ids"):
                probs.append(f"{sec}/{f.get('id')}: fact with zero evidence")
    planned = {q.id for q in state.all_questions()}
    mentioned = {e["question_id"] for e in r["evidence_appendix"]} | {
        q for q in planned if any(q in l for l in r["limitations_and_gaps"])}
    for q in planned - mentioned:
        probs.append(f"planned sub-question {q} appears nowhere in the report")
    open_defects = [d for d in r["qc"].get("defects", []) if d["severity"] in ("high", "medium") and d["type"] != "contradiction"]
    if open_defects and not any("QC defect" in l for l in r["limitations_and_gaps"]):
        probs.append("limitations_and_gaps inconsistent with QC defect list")
    return probs


def render_markdown(r: dict) -> str:
    def finding(f):
        ids = ", ".join(f.get("evidence_ids", [])) or "no evidence"
        return f"- **{BADGE.get(f['claim_type'], f['claim_type'])}** · _{f['confidence']} confidence_ — {f['statement']}  \n  <sub>{f.get('id', '')} · evidence: {ids}</sub>"

    L = [f"# MarketMind Brief — {r['report_id']}", ""]
    if r["status"] != "complete":
        L += [f"> ⚠️ **INCOMPLETE REPORT** — {r.get('incomplete_reason')}", ""]
    ap = r.get("approval")
    L += [f"**Generated:** {r['generated_at']} · **Status:** {r['status']} · "
          f"**Approval:** {(ap['decision'] + ' by ' + ap['approver'] + ' at ' + ap['timestamp']) if ap else 'PENDING — not publishable'}", ""]
    ro = r["research_objective"]
    L += ["## 🎯 Research objective", ro["objective"], ""]
    if ro["assumptions"]:
        L += ["**Recorded assumptions**"] + [f"- {a}" for a in ro["assumptions"]] + [""]
    if ro.get("injection_suspected_in_request"):
        L += ["> 🛡️ The request contained instruction-like text attempting to change the system's controls. It was treated as data; evidence rules and approval remained in force.", ""]
    cl = r["confidence_level"]
    L += ["## 🧭 Executive summary", r["executive_summary"], "",
          f"**Overall confidence: {cl['level'].upper()}** — {cl['rationale']}", ""]
    for key, title in [("market_overview", "🌐 Market overview"), ("key_trends", "📈 Key trends")]:
        L += [f"## {title}"] + ([finding(f) for f in r[key]] or ["_No findings established._"]) + [""]
    m = r["competitor_analysis"]["matrix"]
    L += ["## 🏁 Competitor analysis"]
    if m.get("cells"):
        attrs = m["attributes"]
        L += ["| Vendor | " + " | ".join(a.replace("_", " ") for a in attrs) + " |",
              "|---|" + "---|" * len(attrs)]
        for ent, row in m["cells"].items():
            cells = []
            for a in attrs:
                c = row[a]
                if c["status"] == "NOT_ESTABLISHED":
                    cells.append("⬜ not established")
                else:
                    ids = ",".join(v["evidence_id"] for v in c["values"])
                    txt = c["values"][0]["claim"][:60].replace("|", "/")
                    cells.append(("⚠️ conflicting " if c["status"] == "conflicting" else "") + f"{txt} [{ids}]")
            L.append(f"| **{ent}** | " + " | ".join(cells) + " |")
    else:
        L.append("_No entities established._")
    for n in r["competitor_analysis"]["narratives"]:
        L.append(f"- **{n['entity']}** ({BADGE.get(n['claim_type'])}): {n['narrative']} <sub>[{', '.join(n['evidence_ids'])}]</sub>")
    L.append("")
    for key, title in [("opportunities", "💡 Opportunities"), ("risks", "⚠️ Risks")]:
        L += [f"## {title}"] + ([finding(f) for f in r[key]] or ["_None established._"]) + [""]
    L += ["## ✅ Recommendations"]
    for rec in r["recommendations"]:
        L.append(f"- **{BADGE['recommendation']}** — {rec['statement']}  \n  <sub>{rec['id']} · motivated by: {', '.join(rec['motivated_by'] + rec['evidence_ids'])}</sub>")
    L += ["", "## 🕳️ Limitations and gaps"] + [f"- {x}" for x in r["limitations_and_gaps"]] + [""]
    L += ["## 📎 Evidence appendix", "| ID | Type | Claim | Source | Credibility | Confidence | Recency |", "|---|---|---|---|---|---|---|"]
    for e in r["evidence_appendix"]:
        src = e["source_detail"].get("title") or e["source_detail"].get("operation") or e["source_ref"]
        L.append(f"| {e['evidence_id']} | {BADGE.get(e['claim_type'])} | {e['claim'][:160].replace('|', '/')} | "
                 f"{src} ({e['source_ref']}) | {e['credibility']} | {e['confidence']} | {e['recency']} |")
    L += ["", "## 📚 Sources"] + [f"- `{s['id']}` — {s['title']} ({s['type']}, {s.get('date') or 'undated'})" for s in r["sources"]]
    rc = r["run_cost"]
    L += ["", "## 🧾 Run metadata",
          f"- Models: " + ", ".join(f"{k}={v}" for k, v in r["model_versions"].items()),
          f"- Cost: ${rc['total_usd']:.4f} · Tokens: {rc['total_tokens']:,} · LLM calls: {rc['llm_calls']} · "
          f"Tool calls: {rc['tool_calls']} · Iterations: {rc['iterations']} · Elapsed: {rc['elapsed_s']}s",
          f"- QC verdict: {r['qc'].get('verdict')} (repair round {r['qc'].get('repair_round', 0)})"]
    return "\n".join(L)
