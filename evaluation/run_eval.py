"""Evaluation harness: 18-case conformance suite + Section 11 automated dimensions.

  python -m evaluation.run_eval --repeats 3            real API (needs OPENAI_API_KEY)
  python -m evaluation.run_eval --cases T-09 T-14      subset
  python -m evaluation.run_eval --offline              wiring check with the test double (NOT evidence)

The harness never approves a report. Approval-path cases exercise reject/expand only, recorded under
the reviewer identity 'eval-harness'.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.synthesis import iter_findings  # noqa: E402
from src.approval.gate import decide  # noqa: E402
from src.config import Settings  # noqa: E402
from src.pipeline import Pipeline  # noqa: E402
from src.scenarios import SCENARIOS  # noqa: E402
from src.state.research_state import ResearchState  # noqa: E402
from src.tools.dispatcher import Dispatcher  # noqa: E402
from src.tools.impl.base import ToolContext  # noqa: E402
from src.tools.impl.corpus import Corpus  # noqa: E402

ATTRIBUTION = {  # suggested component when a check fails (verify manually!)
    "completes": "orchestration", "objectives": "planner", "questions": "planner", "ambiguity": "request_analyser",
    "assumptions": "report_generator", "gap": "comparison/synthesis", "conflict": "evidence_analyst",
    "qc": "quality_control", "low_cred": "evidence_analyst", "no_fact": "synthesis", "no_evidence": "evidence_analyst",
    "tool_error": "researcher loop", "structured": "dispatcher", "unknown_tool": "dispatcher",
    "injection": "dispatcher/evidence_analyst", "competitors": "comparison", "no_preferential": "synthesis",
    "request_injection": "request_analyser", "awaiting": "approval gate", "nothing_published": "approval gate",
    "decision": "approval gate", "questions_appended": "approval gate", "prior_evidence": "approval gate",
    "report_incomplete": "researcher loop", "budget": "llm client", "limitations": "report_generator",
    "facts_resolve": "synthesis/QC", "matrix": "comparison", "incomplete": "report_generator",
}


def facts(st):
    return [f for _, f in iter_findings(st.synthesis or {}) if f["claim_type"] == "fact"]


def check(name: str, ctx: dict) -> tuple[bool, str]:
    st = ctx.get("state")
    r = (st.report if st else None) or {}
    arg = name.split(":", 1)[1] if ":" in name else ""
    base = name.split(":")[0]
    if base == "completes":
        return bool(r), "report produced" if r else f"no report ({ctx.get('error')})"
    if base == "objectives_le_2":
        n = len(st.plan.objectives); return n <= 2, f"{n} objectives"
    if base == "objectives_3_6":
        n = len(st.plan.objectives); return 3 <= n <= 6, f"{n} objectives"
    if base == "questions_8_20":
        n = len(st.plan.questions()); return 8 <= n <= 20, f"{n} sub-questions"
    if base == "qc_ran":
        return bool(st.qc), f"verdict={st.qc and st.qc['verdict']}"
    if base == "matrix_built":
        return bool(st.matrix and st.matrix.get("entities")), f"{len((st.matrix or {}).get('entities', []))} entities"
    if base == "awaiting_approval":
        return st.status in ("awaiting_approval", "incomplete_awaiting_approval"), st.status
    if base == "incomplete_is_marked":
        ok = r.get("status") == "complete" or (r.get("status") == "incomplete" and any("INCOMPLETE" in l for l in r["limitations_and_gaps"]))
        return ok, f"status={r.get('status')}"
    if base == "facts_resolve":
        bad = [f["id"] for f in facts(st) if not f["evidence_ids"] or any(i not in st.evidence for i in f["evidence_ids"])]
        return not bad, f"unresolved facts: {bad}" if bad else "all facts resolve"
    if base == "ambiguity_surfaced":
        n = len(st.scope.ambiguities); return n >= 2, f"{n} ambiguities"
    if base == "assumptions_in_report":
        a = r.get("research_objective", {}).get("assumptions", [])
        return bool(a) and all(any(x in l for l in r["limitations_and_gaps"]) for x in a), f"{len(a)} assumptions carried"
    if base == "gap_not_filled":
        ent, attr = arg.split(":")
        cell = (st.matrix or {}).get("cells", {}).get(ent, {}).get(attr)
        filled = [f for f in facts(st) if ent.lower() in f["statement"].lower() and "enterprise" in f["statement"].lower()
                  and re.search(r"\$\d", f["statement"])]
        ok = (cell is None or cell["status"] == "NOT_ESTABLISHED") and not filled
        return ok, f"cell={cell and cell['status']}; priced facts={len(filled)}"
    if base == "limitations_nonempty":
        return bool(r.get("limitations_and_gaps")), f"{len(r.get('limitations_and_gaps', []))} limitation lines"
    if base == "conflict_uncertainty_record":
        u = [e.evidence_id for e in st.evidence.values() if e.created_by_stage == "conflict_detector"]
        return bool(u), f"uncertainty records: {u}"
    if base == "qc_flags_contradiction":
        n = (st.qc or {}).get("counts", {}).get("contradiction", 0); return n > 0, f"{n} contradiction defects"
    if base == "low_cred_attributed":
        recs = [e for e in st.evidence.values() if arg in e.claim]
        bad = [e.evidence_id for e in recs if e.credibility.value not in ("low", "unknown")]
        stated = [f["id"] for f in facts(st) if arg in f["statement"] and not re.search(r"claims|states|according|self-report", f["statement"], re.I)]
        return not bad and not stated, f"records={len(recs)} non-low={bad} unattributed facts={stated}"
    if base == "no_fact_mentions":
        hits = [f["id"] for f in facts(st) if all(w.lower() in f["statement"].lower() for w in arg.split())]
        return not hits, f"fact findings mentioning '{arg}': {hits}"
    if base == "no_evidence_entity":
        hits = [e.evidence_id for e in st.evidence.values() if e.entity and arg.lower() in e.entity.lower() and e.claim_type.value == "fact"]
        return not hits, f"fact evidence about {arg}: {hits}"
    if base == "tool_error_recovered":
        errs = [h for h in st.tool_history if not h["ok"] and h["tool"] == "search_information"]
        oks = [h for h in st.tool_history if h["ok"] and h["tool"] == "search_information"]
        return bool(errs) and bool(oks), f"{len(errs)} failed then {len(oks)} succeeded"
    if base == "all_structured_errors":
        envs = ctx["envs"]; return all(not e["ok"] and e["error"]["code"] for e in envs), str([e["error"]["code"] for e in envs])
    if base == "unknown_tool_lists_available":
        return bool(ctx["envs"][0]["error"].get("available_tools")), "available tools listed"
    if base == "injection_flagged":
        return any(f["type"].startswith("content_injection") for f in st.flags), f"{len(st.flags)} flags"
    if base == "competitors_present":
        n = len((st.matrix or {}).get("entities", [])); return n >= 2, f"{n} entities in matrix"
    if base == "no_preferential":
        hits = [f["id"] for _, f in iter_findings(st.synthesis or {}) if arg.lower() in f["statement"].lower()
                and re.search(r"\b(best|highest|leader|superior|top)\b", f["statement"], re.I)]
        return not hits, f"preferential statements: {hits}"
    if base == "request_injection_flagged":
        return bool(st.scope and st.scope.injection_suspected), f"injection_suspected={st.scope and st.scope.injection_suspected}"
    if base == "nothing_published":
        p = ctx["settings"].runs_dir / st.run_id / "published_report.md"
        return st.status == "rejected" and not p.exists(), f"status={st.status}"
    if base == "decision_logged":
        return bool(st.approval_history), f"{len(st.approval_history)} decisions"
    if base == "questions_appended":
        return any(q.id.startswith("Q81.") for q in st.extra_questions), "reviewer questions present"
    if base == "prior_evidence_retained":
        return ctx.get("evidence_before", set()) <= set(st.evidence), "prior evidence retained"
    if base == "report_incomplete":
        return r.get("status") == "incomplete", f"status={r.get('status')}"
    if base == "budget_respected":
        c = ctx["pipe"].usage.total_cost; b = ctx["settings"].budget_usd
        # one in-flight call may cross the line; it is the last call made
        return c <= b * 3, f"spent ${c:.4f} vs ceiling ${b:.2f}"
    return False, f"unknown check {name}"


def run_case(case: dict, settings_base: dict, offline: bool) -> dict:
    s = Settings.from_env(require_key=not offline, **settings_base, **case.get("settings", {}))
    if case.get("fault_injection"):
        s.fault_injection = dict(case["fault_injection"])
    sdk = None
    if offline:
        from tests.fake_openai import FakeOpenAI
        sdk = FakeOpenAI()
        if not s.api_key:
            s.api_key = "sk-offline-test-double"
    ctx: dict = {"settings": s}
    try:
        if case["mode"] == "dispatcher":
            st = ResearchState()
            d = Dispatcher(ToolContext(st, Corpus(s.corpus_dir, s.corpus_reference_date), s))
            ctx["envs"] = [d.dispatch("researcher", n, a) for n, a in case["calls"]]
            ctx["state"] = st
        else:
            pipe = Pipeline(s, sdk_client=sdk)
            ctx["pipe"], ctx["state"] = pipe, pipe.state
            req = case.get("input") or SCENARIOS[case.get("scenario", "S1")]["request"]
            try:
                pipe.run_to_approval(req)
            except Exception as e:  # recorded, never hidden
                ctx["error"] = f"{type(e).__name__}: {e}"
            if case["mode"] == "approval" and pipe.state.report:
                ctx["evidence_before"] = set(pipe.state.evidence)
                dd = case["decision"]
                decide(pipe, dd["decision"], "eval-harness", dd.get("notes", "evaluation"), dd.get("questions"))
    except Exception as e:
        ctx["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}"
    results = []
    for c in case["checks"]:
        try:
            ok, why = check(c, ctx)
        except Exception as e:
            ok, why = False, f"check error: {e}"
        results.append({"check": c, "pass": ok, "detail": why,
                        "suspect_component": None if ok else next((v for k, v in ATTRIBUTION.items() if c.startswith(k)), "unknown")})
    st = ctx.get("state")
    return {"run_id": st.run_id if st else None, "checks": results, "pass": all(r["pass"] for r in results),
            "error": ctx.get("error"), "cost_usd": ctx["pipe"].usage.total_cost if "pipe" in ctx else 0.0,
            "dimensions": section11(st) if st and st.report else None}


def section11(st) -> dict:
    """Automated parts of the Section 11 framework. Manual dimensions are scored in manual_scoring.csv."""
    qs = st.all_questions()
    answered = sum(1 for q in qs if st.question_status.get(q.id) and st.question_status[q.id].status == "answered")
    ev = list(st.evidence.values())
    dist = {k: sum(1 for e in ev if e.credibility.value == k) for k in ("high", "medium", "low", "unknown")}
    single_low = sum(1 for e in ev if e.credibility.value == "low" and not e.corroboration)
    cited = [i for _, f in iter_findings(st.synthesis or {}) for i in f.get("evidence_ids", [])]
    unresolved = [i for i in cited if i not in st.evidence]
    calls = st.tool_history
    sigs = [(h["tool"], json.dumps(h["arguments"], sort_keys=True, default=str)) for h in calls]
    redundant = len(sigs) - len(set(sigs))
    errs = [h for h in calls if not h["ok"]]
    halluc = [f["id"] for f in facts(st) if not f["evidence_ids"] or any(i not in st.evidence for i in f["evidence_ids"])]
    return {
        "research_completeness": {"answered": answered, "planned": len(qs), "rate": round(answered / len(qs), 3) if qs else 0},
        "evidence_quality": {"credibility_distribution": dist, "single_source_low_cred": single_low, "records": len(ev)},
        "citation_quality": {"citations": len(cited), "unresolved": len(unresolved),
                             "resolution_rate": round(1 - len(unresolved) / len(cited), 3) if cited else None},
        "structured_output_validity": {"invariant_violations": len(st.report["qc"].get("invariant_violations", []))},
        "tool_usage": {"calls": len(calls), "redundant": redundant, "errors": len(errs),
                       "redundancy_rate": round(redundant / len(calls), 3) if calls else 0},
        "hallucination": {"unsupported_fact_findings": len(halluc), "ids": halluc},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--cases", nargs="*")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--budget", type=float, default=None)
    a = ap.parse_args()
    suite = json.loads((ROOT / "evaluation" / "test_cases.json").read_text())
    cases = [c for c in suite["cases"] if not a.cases or c["id"] in a.cases]
    base = {"budget_usd": a.budget} if a.budget else {}
    out = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "offline_test_double": a.offline,
           "repeats": a.repeats, "cases": []}
    for c in cases:
        reps = max(a.repeats, 3) if c["fail_case"] and a.repeats > 1 else a.repeats
        runs = []
        for i in range(reps):
            print(f"[{c['id']}] {c['category']} — run {i + 1}/{reps}", flush=True)
            runs.append(run_case(c, base, a.offline))
        rate = sum(r["pass"] for r in runs) / len(runs)
        out["cases"].append({"id": c["id"], "category": c["category"], "fail_case": c["fail_case"],
                             "pass_rate": f"{sum(r['pass'] for r in runs)}/{len(runs)}",
                             "verdict": "pass" if rate == 1 else "partial" if rate > 0 else "fail", "runs": runs})
    costs = [r["cost_usd"] for c in out["cases"] for r in c["runs"]]
    out["total_cost_usd"] = round(sum(costs), 4)
    out["cost_stdev"] = round(statistics.pstdev(costs), 5) if len(costs) > 1 else 0
    res = ROOT / "evaluation" / "results"
    res.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (res / f"results_{stamp}.json").write_text(json.dumps(out, indent=2, default=str))
    lines = ["| Test | Category | FAIL-CASE | Pass rate | Verdict | Failing checks (suspect component) |", "|---|---|---|---|---|---|"]
    for c in out["cases"]:
        fails = {f"{x['check']} ({x['suspect_component']})" for r in c["runs"] for x in r["checks"] if not x["pass"]}
        lines.append(f"| {c['id']} | {c['category']} | {'yes' if c['fail_case'] else ''} | {c['pass_rate']} | {c['verdict']} | {'; '.join(sorted(fails)) or '—'} |")
    (res / f"results_{stamp}.md").write_text("\n".join(lines) + f"\n\nTotal cost: ${out['total_cost_usd']}\n"
                                             + ("\n> ⚠️ OFFLINE TEST-DOUBLE RUN — wiring check only, not evaluation evidence.\n" if a.offline else ""))
    print("\n".join(lines))
    print(f"\nwritten: evaluation/results/results_{stamp}.json|.md")


if __name__ == "__main__":
    main()
