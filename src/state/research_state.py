"""Serialisable research state: everything the system knows at any moment of a run."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.schemas.evidence import EvidenceRecord
from src.schemas.plan import ResearchPlan, Scope, SubQuestion


class QuestionStatus(BaseModel):
    status: Literal["open", "answered", "unanswerable"] = "open"
    reason: str = ""
    origin: Literal["plan", "repair", "reviewer"] = "plan"
    steps_used: int = 0


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


class ResearchState(BaseModel):
    run_id: str = Field(default_factory=new_run_id)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    request: str = ""
    scope: Optional[Scope] = None
    clarifications: dict[str, str] = Field(default_factory=dict)
    plan: Optional[ResearchPlan] = None
    extra_questions: list[SubQuestion] = Field(default_factory=list)  # repair + reviewer additions
    question_status: dict[str, QuestionStatus] = Field(default_factory=dict)
    evidence: dict[str, EvidenceRecord] = Field(default_factory=dict)
    archived_evidence: dict[str, EvidenceRecord] = Field(default_factory=dict)  # out of scope after rescope
    rejections: list[dict] = Field(default_factory=list)
    tool_results: dict[str, dict] = Field(default_factory=dict)  # result_id -> normalised envelope
    tool_history: list[dict] = Field(default_factory=list)
    tool_call_counts: dict[str, int] = Field(default_factory=dict)
    iteration: int = 0
    tool_calls: int = 0
    stage: str = "created"
    status: Literal["running", "awaiting_approval", "approved", "rejected", "incomplete_awaiting_approval"] = "running"
    incomplete_reason: Optional[str] = None
    termination_reasons: list[str] = Field(default_factory=list)
    repair_round: int = 0
    matrix: Optional[dict] = None
    synthesis: Optional[dict] = None
    qc: Optional[dict] = None
    defects: list[dict] = Field(default_factory=list)
    report: Optional[dict] = None
    approval_history: list[dict] = Field(default_factory=list)
    flags: list[dict] = Field(default_factory=list)  # injection flags etc.
    usage_records: list[dict] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    started_monotonic: float = 0.0
    elapsed_s: float = 0.0

    # ---------------------------------------------------------------- helpers
    def all_questions(self) -> list[SubQuestion]:
        base = self.plan.questions() if self.plan else []
        return base + list(self.extra_questions)

    def question(self, qid: str) -> Optional[SubQuestion]:
        return next((q for q in self.all_questions() if q.id == qid), None)

    def evidence_for(self, qid: str) -> list[EvidenceRecord]:
        return [e for e in self.evidence.values() if e.question_id == qid or qid in e.also_supports]

    def open_questions(self) -> list[SubQuestion]:
        return [q for q in self.all_questions() if self.question_status.get(q.id, QuestionStatus()).status == "open"]

    def next_evidence_id(self) -> str:
        n = len(self.evidence) + len(self.archived_evidence) + 1
        while f"E{n:03d}" in self.evidence or f"E{n:03d}" in self.archived_evidence:
            n += 1
        return f"E{n:03d}"

    def next_result_id(self) -> str:
        return f"R{len(self.tool_history) + 1:04d}"
