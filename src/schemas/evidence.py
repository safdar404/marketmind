"""Evidence record schema (Section 6.2) + the extraction schema used by the Evidence Analyst."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimType(str, Enum):
    fact = "fact"
    inference = "inference"
    recommendation = "recommendation"
    uncertainty = "uncertainty"


class SourceKind(str, Enum):
    retrieved_document = "retrieved_document"
    search_result = "search_result"
    calculation = "calculation"
    model_generated = "model_generated"


class Level(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Credibility(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class Attribute(str, Enum):
    entry_price = "entry_price"
    enterprise_price = "enterprise_price"
    free_tier = "free_tier"
    pricing_model = "pricing_model"
    seat_minimum = "seat_minimum"
    ai_capabilities = "ai_capabilities"
    integrations = "integrations"
    deployment_options = "deployment_options"
    data_residency = "data_residency"
    target_segment = "target_segment"
    funding = "funding"
    market_share = "market_share"
    customer_count = "customer_count"
    market_size = "market_size"
    growth = "growth"
    other = "other"


class EvidenceRecord(Strict):
    evidence_id: str = Field(..., pattern=r"^E\d{3,}$")
    question_id: str
    also_supports: list[str] = Field(default_factory=list)
    claim: str = Field(..., min_length=5, max_length=700)
    claim_type: ClaimType
    entity: Optional[str] = Field(None, max_length=80)
    attribute: Optional[Attribute] = None
    source_ref: str = Field(..., pattern=r"^R\d{4,}$")
    source_kind: SourceKind
    source_detail: dict = Field(default_factory=dict)  # title / document_id / date / source_type
    quote: str = Field("", max_length=600)
    credibility: Credibility
    recency: str = Field(..., description="ISO date or bucket: <1y | 1-3y | 3-5y | >5y | unknown")
    corroboration: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    confidence: Level
    analyst_notes: str = Field("", max_length=600)
    created_by_stage: str = "evidence_analyst"


# ---------------- LLM-facing extraction schema (Evidence Analyst) ----------------
class CandidateClaim(Strict):
    claim: str = Field(..., min_length=5, max_length=500)
    claim_type: ClaimType
    entity: Optional[str] = Field(None, max_length=80)
    attribute: Optional[Attribute] = None
    hit_document_id: Optional[str] = Field(None, max_length=64, description="For search results: which hit")
    quote: str = Field(..., max_length=500, description="Verbatim span copied from the source text")
    supports_claim: bool
    relevance: int = Field(..., ge=0, le=3, description="0 none .. 3 directly answers the sub-question")
    credibility: Credibility
    promotional: bool
    notes: str = Field(..., max_length=300)


class AnalystOutput(Strict):
    candidates: list[CandidateClaim] = Field(default_factory=list, max_length=8)
    injection_detected: bool
