"""Human approval gate. Four explicit outcomes; absence of a decision is never approval.

There is deliberately no auto-approve flag, no default, and no timeout path anywhere in this module.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from src.agents.report_generator import render_markdown
from src.agents.synthesis import iter_findings
from src.schemas.plan import Scope
from src.state.research_state import QuestionStatus
from src.tools.impl.corpus import tokenize

DECISIONS = ("approve", "reject", "expand", "rescope")
SCOPE_FIELDS = ("entity_type", "segment", "geography", "time_horizon", "deliverable_type", "normalised_objective")


class ApprovalError(ValueError):
    pass


def reviewer_brief(state) -> dict:
    """What a reviewer needs to decide in under two minutes - shown BEFORE the full draft."""
    r = state.report or {}
    counts = {"fact": 0, "inference": 0, "recommendation": 0, "uncertainty": 0}
    for _, f in iter_findings(state.synthesis or {}):
        counts[f["claim_type"]] = counts.get(f["claim_type"], 0) + 1
    qc = state.qc or {}
    return {
        "objective": (r.get("research_objective") or {}).get("objective"),
        "assumptions": (r.get("research_objective") or {}).get("assumptions", []),
        "report_status": r.get("status"), "incomplete_reason": r.get("incomplete_reason"),
        "qc_verdict": qc.get("verdict"),
        "outstanding_defects": [d for d in qc.get("defects", []) if d["severity"] in ("high", "medium")],
        "confidence": r.get("confidence_level"),
        "claims_by_type": counts,
        "limitations": r.get("limitations_and_gaps", []),
        "injection_flags": state.flags,
    }


def _snapshot(state) -> str:
    return hashlib.sha256(json.dumps(state.report, sort_keys=True, default=str).encode()).hexdigest()


def _record(pipe, decision: str, approver: str, notes: str, extra: dict | None = None):
    st = pipe.state
    row = {"decision": decision, "approver": approver, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "notes": notes, "report_sha256": _snapshot(st), "report_status": (st.report or {}).get("status"),
           "qc_verdict": (st.qc or {}).get("verdict"), **(extra or {})}
    st.approval_history.append(row)
    pipe.log.event("approval_decision", "approval", **row)
    d = pipe.settings.runs_dir / st.run_id
    (d / f"decision_{len(st.approval_history):02d}_{decision}.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    return row


def decide(pipe, decision: str, approver: str, notes: str = "", questions: list[str] | None = None,
           scope_changes: dict | None = None) -> dict:
    st = pipe.state
    if decision not in DECISIONS:
        raise ApprovalError(f"Unknown decision '{decision}'. Choose one of {DECISIONS}.")
    approver = (approver or "").strip()
    if len(approver) < 2:
        raise ApprovalError("A named approver is required for every decision.")
    if st.status not in ("awaiting_approval", "incomplete_awaiting_approval") or not st.report:
        raise ApprovalError(f"Run is not awaiting approval (status: {st.status}).")
    d = pipe.settings.runs_dir / st.run_id

    if decision == "approve":
        row = _record(pipe, "approve", approver, notes)
        st.report["approval"] = {"approver": approver, "decision": "approved", "timestamp": row["timestamp"], "notes": notes}
        st.status = "approved"
        st.stage = "published"
        (d / "published_report.json").write_text(json.dumps(st.report, indent=2, default=str), encoding="utf-8")
        (d / "published_report.md").write_text(render_markdown(st.report), encoding="utf-8")
        pipe.save()
        return {"status": "approved", "published": str(d / "published_report.md")}

    if decision == "reject":
        if not notes.strip():
            raise ApprovalError("A rejection reason is required.")
        _record(pipe, "reject", approver, notes)
        st.status = "rejected"
        st.stage = "archived_rejected"
        pipe.save()
        return {"status": "rejected", "published": None}

    if decision == "expand":
        qs = [q.strip() for q in (questions or []) if q and q.strip()]
        if not 1 <= len(qs) <= 5:
            raise ApprovalError("Provide 1-5 specific additional questions.")
        _record(pipe, "expand", approver, notes, {"questions": qs})
        n = 80 + sum(1 for h in st.approval_history if h["decision"] == "expand")
        ids = pipe._add_questions(qs, "reviewer", n)
        st.incomplete_reason = None
        st.termination_reasons = []
        reason = pipe.research(only=ids)
        pipe.analyse_and_report()
        return {"status": st.status, "new_questions": sorted(ids), "loop_reason": reason}

    # rescope
    changes = {k: v.strip()[:600] for k, v in (scope_changes or {}).items() if k in SCOPE_FIELDS and v and v.strip()}
    if not changes:
        raise ApprovalError(f"Provide at least one scope change among {SCOPE_FIELDS}.")
    _record(pipe, "rescope", approver, notes, {"scope_changes": changes})
    scope = Scope.model_validate({**st.scope.model_dump(), **changes})
    st.scope = scope
    st.extra_questions = []
    pipe.plan({})
    retained, archived = _retain_evidence(st)
    pipe.log.event("rescope_retention", "approval", retained=retained, archived=archived,
                   rule="keep a record iff it shares >=2 content tokens with a new sub-question (or its entity is a named entity); remap to the best match")
    st.incomplete_reason = None
    st.termination_reasons = []
    pipe.research()
    pipe.analyse_and_report()
    return {"status": st.status, "retained": retained, "archived": archived}


def _retain_evidence(st) -> tuple[list[str], list[str]]:
    """Retention rule: evidence stays if still in scope (shares >=2 content tokens with a regenerated
    sub-question, or concerns an entity named in the new scope); it is remapped to its best-matching new
    question. Everything else moves to archived_evidence - never deleted, so it stays auditable."""
    qs = st.all_questions()
    named = {n.casefold() for n in (st.scope.named_entities or [])}
    retained, archived = [], []
    for eid, e in list(st.evidence.items()):
        toks = set(tokenize(e.claim + " " + (e.entity or "")))
        best, score = None, 0
        for q in qs:
            s = len(toks & set(tokenize(q.text)))
            if s > score:
                best, score = q, s
        if best and (score >= 2 or (e.entity and e.entity.casefold() in named)):
            e.question_id, e.also_supports = best.id, []
            retained.append(eid)
        else:
            st.archived_evidence[eid] = st.evidence.pop(eid)
            archived.append(eid)
    for q in qs:
        if st.evidence_for(q.id):
            st.question_status[q.id] = QuestionStatus(status="answered", reason="retained in-scope evidence after rescope")
    return retained, archived
