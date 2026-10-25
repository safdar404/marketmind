"""Quality-Control Agent. Diagnoses, never repairs.

Mechanical checks run in CODE (deterministic checks do not hallucinate):
  unsupported_claim  - fact with zero evidence ids or an id that does not resolve
  missing_source     - evidence whose source_ref does not resolve; cited ids absent from the store
  coverage_gap       - planned sub-question with no evidence, or evidence never used in the report
Hybrid:
  low_confidence     - a section resting entirely on low-credibility / single-source evidence
Model:
  contradiction      - findings that cannot both be true (+ conflicts already detected in code)
"""
from __future__ import annotations

import json

from src.agents.synthesis import SECTIONS, iter_findings
from src.prompts import quality_control as P
from src.schemas.report import ContradictionCheck

_SEV = {"high": 3, "medium": 2, "low": 1}


def _d(dtype, severity, location, detail, gap_question=None, by="code"):
    return {"type": dtype, "severity": severity, "location": location, "detail": detail,
            "gap_question": gap_question, "detected_by": by}


def mechanical_checks(state, synth: dict) -> list[dict]:
    defects: list[dict] = []
    ev = state.evidence
    cited: set[str] = set()
    # unsupported claims + missing sources in the draft
    for sec, f in iter_findings(synth):
        ids = f.get("evidence_ids", [])
        cited.update(ids)
        bad = [i for i in ids if i not in ev]
        loc = f"{sec}/{f.get('id')}"
        if f["claim_type"] == "fact" and (not ids or bad):
            defects.append(_d("unsupported_claim", "high", loc,
                              f"fact '{f['statement'][:120]}' has {'no evidence ids' if not ids else 'unresolvable ids ' + str(bad)}",
                              f"Find a source that directly states: {f['statement'][:200]}"))
        elif bad:
            defects.append(_d("missing_source", "medium", loc, f"cites evidence ids not in the store: {bad}"))
        elif not ids and f["claim_type"] in ("inference", "recommendation"):
            defects.append(_d("unsupported_claim", "medium", loc,
                              f"{f['claim_type']} '{f['statement'][:100]}' states no evidential basis"))
    # evidence records must resolve to real tool results
    for e in ev.values():
        if e.source_ref not in state.tool_results:
            defects.append(_d("missing_source", "high", f"evidence/{e.evidence_id}",
                              f"source_ref {e.source_ref} does not resolve to a tool result"))
    # coverage: plan-to-report diff
    for q in state.all_questions():
        st = state.question_status.get(q.id)
        recs = state.evidence_for(q.id)
        if not recs:
            if st and st.status == "unanswerable":
                defects.append(_d("coverage_gap", "low", f"plan/{q.id}",
                                  f"declared unanswerable: {st.reason[:150]}", None))
            else:
                defects.append(_d("coverage_gap", "high", f"plan/{q.id}", f"no evidence for planned question: {q.text}",
                                  q.text))
        elif not any(r.evidence_id in cited for r in recs):
            defects.append(_d("coverage_gap", "medium", f"plan/{q.id}",
                              f"evidence exists ({', '.join(r.evidence_id for r in recs[:4])}) but no report section uses it"))
    # low confidence (hybrid, computed here)
    for sec in SECTIONS:
        ids = {i for f in synth.get(sec, []) for i in f.get("evidence_ids", []) if i in ev}
        if ids and all(ev[i].credibility.value in ("low", "unknown") for i in ids):
            defects.append(_d("low_confidence", "medium", sec, f"section rests entirely on low-credibility evidence {sorted(ids)}"))
        elif len(ids) == 1 and synth.get(sec):
            only = next(iter(ids))
            if ev[only].credibility.value != "high":
                defects.append(_d("low_confidence", "low", sec, f"section rests on a single non-high-credibility source ({only})"))
    # contradictions already detected structurally - surfaced, not resolved
    for e in ev.values():
        if e.claim_type.value == "uncertainty" and e.created_by_stage == "conflict_detector":
            used = e.evidence_id in cited
            defects.append(_d("contradiction", "low" if used else "medium", f"evidence/{e.evidence_id}",
                              ("surfaced in report: " if used else "NOT surfaced in report: ") + e.claim[:200]))
    return defects


def model_contradictions(client, synth: dict) -> list[dict]:
    items = [{"id": f.get("id"), "type": f["claim_type"], "statement": f["statement"]}
             for _, f in iter_findings(synth) if f["claim_type"] in ("fact", "inference")]
    if len(items) < 2:
        return []
    out, _ = client.structured("quality_control", [
        {"role": "system", "content": P.SYSTEM},
        {"role": "user", "content": "Findings (data):\n" + json.dumps(items, indent=1)}],
        ContradictionCheck, "contradiction_check", fallback=lambda: ContradictionCheck())
    ids = {i["id"] for i in items}
    return [_d("contradiction", "high", f"{c.finding_a} vs {c.finding_b}", c.explanation,
               f"Which source is authoritative for the quantity disputed between {c.finding_a} and {c.finding_b}?", by="model")
            for c in out.contradictions if c.finding_a in ids and c.finding_b in ids]


def run_qc(client, state, log=None, use_model: bool = True) -> dict:
    synth = state.synthesis or {}
    defects = mechanical_checks(state, synth)
    if use_model:
        try:
            defects += model_contradictions(client, synth)
        except Exception as e:  # QC model failure must not hide the mechanical results
            defects.append(_d("qc_error", "low", "quality_control", f"model contradiction check failed: {e}"))
    for i, d in enumerate(defects, 1):
        d["id"] = f"D{i}"
    blocking = [d for d in defects if d["severity"] == "high"]
    verdict = {"verdict": "fail" if blocking else "pass", "defects": defects,
               "counts": {t: sum(1 for d in defects if d["type"] == t) for t in
                          ["unsupported_claim", "missing_source", "coverage_gap", "contradiction", "low_confidence"]},
               "gap_questions": [d["gap_question"] for d in blocking if d.get("gap_question")],
               "repair_round": state.repair_round}
    state.qc = verdict
    if log:
        log.event("qc", "quality_control", verdict=verdict["verdict"], counts=verdict["counts"],
                  blocking=len(blocking), repair_round=state.repair_round)
    return verdict
