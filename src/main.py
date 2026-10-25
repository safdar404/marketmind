"""MarketMind CLI.

  python -m src.main smoke                         one real API call, masked key, tokens + cost
  python -m src.main run --scenario S1             full run up to the human gate, then CLI approval
  python -m src.main run --request "..." --max-iterations 3     (partial-report demo)
  python -m src.main resume --run-id <id>          reopen a run waiting at the gate
  python -m src.main adversarial                   dispatcher adversarial calls (no API key needed)
  python -m src.main export-schemas                write JSON Schema files to docs/schemas/
"""
from __future__ import annotations

import argparse
import json
import sys

from src.config import ROOT, ConfigError, Settings, mask_key
from src.scenarios import SCENARIOS


def _settings(args, require_key=True) -> Settings:
    over = {}
    if getattr(args, "max_iterations", None):
        over["max_iterations"] = args.max_iterations
    if getattr(args, "budget", None):
        over["budget_usd"] = args.budget
    return Settings.from_env(require_key=require_key, **over)


def cmd_smoke(args):
    from src.llm.client import LLMError, smoke_test
    s = _settings(args)
    print(f"key: {mask_key(s.api_key)}")
    try:
        print(json.dumps(smoke_test(s), indent=2))
    except LLMError as e:
        sys.exit(f"[smoke] {e.kind}: {e.message}")


def cmd_run(args):
    from src.approval.cli_gate import cli_gate
    from src.pipeline import Pipeline
    s = _settings(args)
    request = args.request or SCENARIOS[args.scenario]["request"]
    pipe = Pipeline(s)
    print(f"run_id: {pipe.state.run_id}")
    scope = pipe.analyse(request)
    answers = {}
    for a in scope.ambiguities:
        if a.resolution.value == "clarify":
            ans = input(f"[clarify:{a.dimension}] {a.clarification_question}\n  (blank = assume '{a.default_assumption}'): ").strip()
            answers[a.dimension] = ans
    pipe.plan(answers)
    reason = pipe.research()
    print(f"research loop ended: {reason}")
    pipe.analyse_and_report()
    print(json.dumps(pipe.usage.summary(), indent=2))
    print(cli_gate(pipe))


def cmd_resume(args):
    from src.approval.cli_gate import cli_gate
    from src.pipeline import Pipeline
    from src.state.persistence import load_state
    s = _settings(args)
    pipe = Pipeline(s, state=load_state(s.runs_dir, args.run_id))
    print(cli_gate(pipe))


def cmd_adversarial(args):
    from src.tools.dispatcher import Dispatcher
    from src.tools.impl.base import ToolContext
    from src.tools.impl.corpus import Corpus
    from src.state.research_state import ResearchState
    s = _settings(args, require_key=False)
    st = ResearchState()
    d = Dispatcher(ToolContext(st, Corpus(s.corpus_dir, s.corpus_reference_date), s))
    cases = [("unknown tool", "researcher", "delete_database", "{}"),
             ("malformed JSON", "researcher", "search_information", '{"query": "pricing", '),
             ("out-of-enum", "researcher", "search_information", '{"query":"pricing","source_type":"blog","max_results":3,"recency_window":"any"}'),
             ("out-of-bounds", "researcher", "search_information", '{"query":"pricing","source_type":"any","max_results":500,"recency_window":"any"}'),
             ("path traversal", "researcher", "retrieve_document", '{"document_id":"../../.env","section":null}'),
             ("write tool out of stage", "researcher", "save_research", '{"question_id":"Q1.1","claim":"x is y","claim_type":"fact","source_ref":"R0001","confidence":"high","credibility":"high"}'),
             ("fabricated source_ref", "evidence_analyst", "save_research", '{"question_id":"Q1.1","claim":"Vendor charges $10","claim_type":"fact","source_ref":"R9999","confidence":"high","credibility":"high","quote":"$10"}')]
    for label, stage, name, raw in cases:
        env = d.dispatch(stage, name, raw)
        print(f"{label:26s} -> ok={env['ok']}  error={json.dumps(env['error'])[:160]}")
    print("process still running: True")


def cmd_export(args):
    from src.schemas.evidence import EvidenceRecord
    from src.schemas.plan import ResearchPlan, Scope
    from src.schemas.report import Report
    from src.tools.registry import REGISTRY
    out = ROOT / "docs" / "schemas"
    out.mkdir(parents=True, exist_ok=True)
    for name, m in {"scope": Scope, "research_plan": ResearchPlan, "evidence_record": EvidenceRecord, "report": Report}.items():
        (out / f"{name}.schema.json").write_text(json.dumps(m.model_json_schema(), indent=2))
    tools = {n: {"permission": t.permission, "allowed_stages": sorted(t.allowed_stages), "budget": t.budget,
                 "timeout_s": t.timeout_s, "description": t.description, "abuse_case": t.abuse_case,
                 "mitigation": t.mitigation, "arguments_schema": t.args_model.model_json_schema()} for n, t in REGISTRY.items()}
    (out / "tools.schema.json").write_text(json.dumps(tools, indent=2))
    print(f"wrote schemas to {out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="marketmind")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("smoke")
    r = sub.add_parser("run")
    r.add_argument("--scenario", default="S1", choices=sorted(SCENARIOS))
    r.add_argument("--request")
    r.add_argument("--max-iterations", type=int)
    r.add_argument("--budget", type=float)
    rs = sub.add_parser("resume")
    rs.add_argument("--run-id", required=True)
    sub.add_parser("adversarial")
    sub.add_parser("export-schemas")
    args = p.parse_args(argv)
    try:
        {"smoke": cmd_smoke, "run": cmd_run, "resume": cmd_resume, "adversarial": cmd_adversarial,
         "export-schemas": cmd_export}[args.cmd](args)
    except ConfigError as e:
        sys.exit(f"[config] {e}")


if __name__ == "__main__":
    main()
