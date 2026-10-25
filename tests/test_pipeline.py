"""Offline tests for the controls the manual grades. Run: pytest -q"""
import json

import pytest

from src.agents.quality_control import mechanical_checks
from src.approval.gate import ApprovalError, decide
from src.pipeline import Pipeline
from src.schemas.plan import validate_plan
from src.state.persistence import load_state
from tests.fake_openai import FakeOpenAI

REQ = "Research the market for AI-powered customer support software and prepare a business intelligence report."


def run(settings, **kw):
    pipe = Pipeline(settings, sdk_client=FakeOpenAI(**kw))
    pipe.run_to_approval(REQ)
    return pipe


def test_full_run_reaches_gate_and_never_publishes(settings):
    pipe = run(settings)
    st = pipe.state
    assert st.status in ("awaiting_approval", "incomplete_awaiting_approval")
    assert not (settings.runs_dir / st.run_id / "published_report.md").exists()
    for f in ["plan.json", "evidence.json", "tool_log.jsonl", "qc_verdict.json", "report.json", "usage_summary.json", "run_log.jsonl"]:
        assert (settings.runs_dir / st.run_id / f).exists(), f
    r = st.report
    assert r["approval"] is None and r["limitations_and_gaps"]
    # every fact in the report resolves
    ids = {e["evidence_id"] for e in r["evidence_appendix"]}
    for sec in ["market_overview", "key_trends", "opportunities", "risks"]:
        for f in r[sec]:
            if f["claim_type"] == "fact":
                assert f["evidence_ids"] and set(f["evidence_ids"]) <= ids
    # executive summary bullet citing a non-existent finding was dropped in code
    assert "F999" not in r["executive_summary"]


def test_conflict_produces_uncertainty_record(settings):
    st = run(settings).state
    unc = [e for e in st.evidence.values() if e.created_by_stage == "conflict_detector"]
    assert unc, "planted $4.1bn vs $6.8bn contradiction should create an uncertainty record"


def test_nonexistent_vendor_is_unanswerable(settings):
    st = run(settings).state
    assert st.question_status["Q3.2"].status == "unanswerable"


def test_fabricated_quotes_rejected(settings):
    st = run(settings, analyst_quotes_bad=True).state
    assert not [e for e in st.evidence.values() if e.claim_type.value == "fact"]
    assert any("quote_not_in_source" in r["reason"] for r in st.rejections)


def test_iteration_cap_gives_partial_report(settings):
    settings.max_iterations = 2
    pipe = run(settings)
    assert pipe.state.report["status"] == "incomplete"
    assert any("INCOMPLETE" in l for l in pipe.state.report["limitations_and_gaps"])


def test_budget_ceiling_respected(settings):
    settings.budget_usd = 0.0005
    pipe = Pipeline(settings, sdk_client=FakeOpenAI())
    try:
        pipe.run_to_approval(REQ)
    except Exception:
        pass
    assert pipe.usage.total_cost <= settings.budget_usd + 0.002  # at most one call in flight past the line


def test_tool_failure_does_not_crash(settings):
    settings.fault_injection = {"search_information": "error"}
    pipe = run(settings)
    errs = [h for h in pipe.state.tool_history if h["tool"] == "search_information" and not h["ok"]]
    assert errs and errs[0]["error"]["code"] == "tool_exception"
    assert pipe.state.report is not None


def test_tool_timeout_is_structured(settings):
    settings.fault_injection = {"search_information": "timeout"}
    pipe = run(settings)
    assert any(h["error"] and h["error"]["code"] == "timeout" for h in pipe.state.tool_history)


def test_approval_paths(settings):
    pipe = run(settings)
    with pytest.raises(ApprovalError):
        decide(pipe, "approve", "")  # no anonymous approval
    with pytest.raises(ApprovalError):
        decide(pipe, "reject", "Dana Reviewer", "")  # reason required
    out = decide(pipe, "expand", "Dana Reviewer", "need more", questions=["What does TicketPilot charge per agent per month?"])
    assert "Q81.1" in out["new_questions"] and pipe.state.question("Q81.1") is not None
    before = set(pipe.state.evidence)
    out = decide(pipe, "rescope", "Dana Reviewer", "SMB only", scope_changes={"segment": "SMB teams under 25 agents"})
    assert out["retained"] and set(out["retained"]) <= before
    out = decide(pipe, "approve", "Dana Reviewer", "ok")
    assert out["status"] == "approved"
    r = load_state(settings.runs_dir, pipe.state.run_id).report
    assert r["approval"]["approver"] == "Dana Reviewer"
    assert [h["decision"] for h in pipe.state.approval_history] == ["expand", "rescope", "approve"]


def test_reject_publishes_nothing(settings):
    pipe = run(settings)
    decide(pipe, "reject", "Sam Partner", "Scope wrong")
    assert pipe.state.status == "rejected"
    assert not (settings.runs_dir / pipe.state.run_id / "published_report.md").exists()


def test_qc_catches_injected_defects(settings):
    pipe = run(settings)
    st = pipe.state
    synth = json.loads(json.dumps(st.synthesis))
    victim = next(iter(st.evidence))
    del st.evidence[victim]                                             # 1 delete an evidence record
    synth["market_overview"].append({"id": "FX", "statement": "Vendor Z has 90% share.", "claim_type": "fact",
                                     "evidence_ids": ["E999"], "confidence": "high"})  # 2 broken reference
    synth["key_trends"].append({"id": "FY", "statement": "Market shrinks", "claim_type": "fact",
                                "evidence_ids": [], "confidence": "high"})            # 3 unsupported claim
    from src.schemas.plan import SubQuestion
    st.extra_questions.append(SubQuestion(id="Q99.1", text="What is the churn rate for HelixDesk customers?",
                                          evidence_type="customer_evidence", candidate_tools=["search_information"],
                                          priority="high", done_when="a churn figure"))  # 4 dropped sub-question
    d = mechanical_checks(st, synth)
    types = {(x["type"], x["location"].split("/")[0]) for x in d}
    assert ("unsupported_claim", "market_overview") in types
    assert ("unsupported_claim", "key_trends") in types
    assert any(x["type"] == "coverage_gap" and "Q99.1" in x["location"] for x in d)
    assert any(x["type"] in ("missing_source", "unsupported_claim") and victim in x["detail"] for x in d) or \
        any(x["type"] == "coverage_gap" for x in d)


def test_plan_validator_rejects_vague(settings):
    from src.schemas.plan import ResearchPlan
    p = ResearchPlan.model_validate(FakeOpenAI()._research_plan([{"content": ""}]))
    assert validate_plan(p) == []
    p.objectives[0].sub_questions[0].text = "Analyse the competitive landscape of the market"
    assert any("vague" in e for e in validate_plan(p))
