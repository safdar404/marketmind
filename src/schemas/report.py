"""Synthesis output (LLM-facing) and the final report schema (Section 6.1)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.evidence import ClaimType, EvidenceRecord, Level


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Finding(Strict):
    id: str = ""
    statement: str = Field(..., min_length=5, max_length=700)
    claim_type: ClaimType
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    confidence: Level
    objective_id: Optional[str] = None


class Recommendation(Strict):
    id: str = ""
    statement: str = Field(..., min_length=5, max_length=700)
    claim_type: ClaimType = ClaimType.recommendation
    motivated_by: list[str] = Field(default_factory=list, description="Finding ids or evidence ids")
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Level


class EntityNarrative(Strict):
    entity: str
    narrative: str = Field(..., max_length=900)
    claim_type: ClaimType
    evidence_ids: list[str] = Field(default_factory=list)


class SynthesisOutput(Strict):
    market_overview: list[Finding] = Field(default_factory=list, max_length=8)
    key_trends: list[Finding] = Field(default_factory=list, max_length=8)
    competitor_narratives: list[EntityNarrative] = Field(default_factory=list, max_length=12)
    opportunities: list[Finding] = Field(default_factory=list, max_length=6)
    risks: list[Finding] = Field(default_factory=list, max_length=6)
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=6)


class SummaryBullet(Strict):
    text: str = Field(..., max_length=400)
    finding_ids: list[str] = Field(..., min_length=1)


class ExecutiveSummary(Strict):
    bullets: list[SummaryBullet] = Field(..., min_length=1, max_length=8)


class ContradictionPair(Strict):
    finding_a: str
    finding_b: str
    explanation: str = Field(..., max_length=300)


class ContradictionCheck(Strict):
    contradictions: list[ContradictionPair] = Field(default_factory=list, max_length=10)


class Approval(Strict):
    approver: str = Field(..., min_length=2, max_length=80)
    decision: str
    timestamp: str
    notes: str = ""


class ConfidenceLevel(Strict):
    level: Level
    rationale: str


class Report(Strict):
    report_id: str
    generated_at: str
    status: str = Field(..., pattern=r"^(complete|incomplete)$")
    incomplete_reason: Optional[str] = None
    model_versions: dict
    run_cost: dict
    research_objective: dict  # objective, assumptions[], unresolved_ambiguities[], clarifications{}
    executive_summary: str = Field(..., min_length=10)
    market_overview: list[Finding]
    key_trends: list[Finding]
    competitor_analysis: dict  # matrix + narratives
    opportunities: list[Finding]
    risks: list[Finding]
    evidence_appendix: list[EvidenceRecord]
    recommendations: list[Recommendation]
    confidence_level: ConfidenceLevel
    limitations_and_gaps: list[str]
    sources: list[dict]
    qc: dict
    approval: Optional[Approval] = None
