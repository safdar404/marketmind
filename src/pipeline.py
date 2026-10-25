"""Stage orchestration: analyse -> plan -> research loop -> comparison -> synthesis -> QC
-> (bounded repair) -> report -> HUMAN approval. Never publishes on its own."""
from __future__ import annotations

import time
from functools import lru_cache

from src.agents.comparison import build_matrix
from src.agents.evidence_analyst import EvidenceAnalyst
from src.agents.planner import make_plan
from src.agents.quality_control import run_qc
from src.agents.report_generator import assemble, render_markdown
from src.agents.request_analyser import analyse_request, apply_clarifications
from src.agents.researcher import ResearchAgent
from src.agents.synthesis import synthesise
from src.config import Settings
from src.llm.client import LLMClient
from src.llm.usage import UsageTracker
from src.logging_setup import RunLogger
from src.schemas.plan import EvidenceType, Priority, ResearchToolName, SubQuestion
from src.state.persistence import save_state
from src.state.research_state import QuestionStatus, ResearchState
from src.tools.dispatcher import Dispatcher
from src.tools.impl.base import ToolContext
from src.tools.impl.corpus import Corpus


class PipelineError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def get_corpus(corpus_dir: str, ref: str) -> Corpus:
    return Corpus(corpus_dir, ref)


class Pipeline:
    def __init__(self, settings: Settings, state: ResearchState | None = None, on_event=None, sdk_client=None):
        self.settings = settings
        self.state = state or ResearchState()
        self.log = RunLogger(self.state.run_id, settings.runs_dir, settings.log_level, on_event)
        self.usage = UsageTracker(settings, self.state.run_id)
        if self.state.usage_records:
            self.usage.load(self.state.usage_records)
        self.client = LLMClient(settings, self.usage, self.log, sdk_client=sdk_client)
        self.corpus = get_corpus(str(settings.corpus_dir), settings.corpus_reference_date)
        self.ctx = ToolContext(self.state, self.corpus, settings, self.log,
                               report_builder=lambda sections: assemble(self.client, self.state, self.usage, self.log, sections))
        self.dispatcher = Dispatcher(self.ctx)
        self.analyst = EvidenceAnalyst(self.client, self.dispatcher, self.state, self.log)
        self.state.model_versions = dict(settings.models)
        self._t0 = time.perf_counter()

    # ------------------------------------------------------------------ utilities
    def save(self):
        self.state.usage_records = self.usage.to_list()
        self.state.elapsed_s += time.perf_counter() - self._t0
        self._t0 = time.perf_counter()
        save_state(self.state, self.settings.runs_dir, self.usage.summary())

    def _stage(self, name: str):
        self.state.stage = name
        self.log.event("stage", name)

    # ------------------------------------------------------------------ stages
    def analyse(self, request: str):
        self._stage("request_analyser")
        self.state.request = request
        self.state.scope = analyse_request(self.client, request, self.log)
        self.save()
        return self.state.scope

    def plan(self, clarifications: dict | None = None):
        if not self.state.scope:
            raise PipelineError("Analyse the request before planning.")
        self._stage("planner")
        if clarifications:
            self.state.clarifications.update({k: v for k, v in clarifications.items() if v})
            apply_clarifications(self.state.scope, clarifications)
        plan, _ = make_plan(self.client, self.state.scope, self.state.clarifications, self.log)
        self.state.plan = plan
        self.state.question_status = {q.id: QuestionStatus() for q in plan.questions()}
        self.save()
        return plan

    def research(self, only: set[str] | None = None) -> str:
        if not self.state.plan:
            raise PipelineError("Generate a plan before researching.")
        self._stage("researcher")
        self.state.status = "running"
        agent = ResearchAgent(self.client, self.dispatcher, self.analyst, self.state, self.settings, self.log)
        reason = agent.run(only)
        self.save()
        return reason

    def _add_questions(self, texts: list[str], origin: str, obj_no: int, etypes: list | None = None) -> set[str]:
        ids = set()
        for i, t in enumerate(texts, 1):
            t = t.strip()[:300]
            if len(t) < 15:
                t = (t + " — find a source that addresses this")[:300]
            q = SubQuestion(id=f"Q{obj_no}.{i}", text=t,
                            evidence_type=(etypes[i - 1] if etypes and i <= len(etypes) and etypes[i - 1] else EvidenceType.company_profile),
                            candidate_tools=[ResearchToolName.search_information, ResearchToolName.retrieve_document],
                            priority=Priority.high, done_when="A source states it, or the corpus is shown not to contain it")
            self.state.extra_questions.append(q)
            self.state.question_status[q.id] = QuestionStatus(origin=origin)
            ids.add(q.id)
        return ids

    def analyse_and_report(self) -> dict:
        """comparison -> synthesis -> QC -> bounded repair loop -> report draft (awaiting approval)."""
        feedback = None
        while True:
            self._stage("comparison")
            build_matrix(self.dispatcher, self.state, self.log)
            self._stage("synthesis")
            synthesise(self.client, self.state, feedback, self.log)
            self._stage("quality_control")
            qc = run_qc(self.client, self.state, self.log)
            self.save()
            if qc["verdict"] == "pass":
                break
            if self.state.repair_round >= self.settings.max_repair_rounds:
                self.log.event("repair_exhausted", "quality_control", "WARNING", rounds=self.state.repair_round,
                               outstanding=[d["id"] for d in qc["defects"] if d["severity"] == "high"])
                break
            if self.client.usage.total_cost >= self.settings.budget_usd:
                self.log.event("repair_skipped", "quality_control", "WARNING", reason="budget_ceiling")
                break
            self.state.repair_round += 1
            gaps = [g for g in qc["gap_questions"] if g][:4]
            feedback = [d for d in qc["defects"] if d["severity"] == "high"]
            self.log.event("repair_round", "quality_control", round=self.state.repair_round, gap_questions=gaps)
            if gaps:
                ids = self._add_questions(gaps, "repair", 90 + self.state.repair_round)
                self.research(only=ids)
        self._stage("report_generator")
        env = self.dispatcher.dispatch("report_generator", "generate_report", {"run_id": self.state.run_id})
        if not env["ok"]:
            self.save()
            raise PipelineError(f"Report generation failed: {env['error']['message']}")
        self.state.status = "awaiting_approval" if self.state.incomplete_reason is None else "incomplete_awaiting_approval"
        self.state.stage = "awaiting_approval"
        self.log.event("awaiting_approval", "approval", report_status=self.state.report["status"])
        self.save()
        (self.settings.runs_dir / self.state.run_id / "report_draft.md").write_text(
            render_markdown(self.state.report), encoding="utf-8")
        return self.state.report

    def run_to_approval(self, request: str, clarifications: dict | None = None) -> dict:
        """Headless path used by the CLI and the evaluation harness. Stops AT the gate."""
        self.analyse(request)
        self.plan(clarifications or {})
        self.research()
        return self.analyse_and_report()
