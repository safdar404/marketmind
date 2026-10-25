"""Strict argument schemas for every tool. extra='forbid' == additionalProperties: false."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.evidence import Attribute, ClaimType, Credibility, Level


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceType(str, Enum):
    any = "any"
    vendor_page = "vendor_page"
    pricing_page = "pricing_page"
    press = "press"
    analyst_note = "analyst_note"
    review = "review"


class Recency(str, Enum):
    y1 = "1y"
    y3 = "3y"
    y5 = "5y"
    any = "any"


class SearchArgs(Args):
    query: str = Field(..., min_length=2, max_length=200)
    source_type: SourceType
    max_results: int = Field(..., ge=1, le=10)
    recency_window: Recency


class RetrieveArgs(Args):
    document_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_\-]{2,63}$")
    section: Optional[str] = Field(None, max_length=80)


class Operation(str, Enum):
    growth_rate = "growth_rate"
    cagr = "cagr"
    share = "share"
    ratio = "ratio"
    average = "average"
    sum = "sum"
    difference = "difference"
    minimum = "minimum"
    maximum = "maximum"


class CalculateArgs(Args):
    operation: Operation
    values: list[float] = Field(..., min_length=1, max_length=24)
    period: Optional[int] = Field(None, ge=1, le=50)


class CompareArgs(Args):
    entities: list[str] = Field(..., min_length=1, max_length=10)
    attributes: list[Attribute] = Field(..., min_length=1, max_length=16)


class SaveArgs(Args):
    question_id: str = Field(..., pattern=r"^Q[\w.]+$")
    claim: str = Field(..., min_length=5, max_length=700)
    claim_type: ClaimType
    source_ref: str = Field(..., pattern=r"^R\d{4,}$")
    confidence: Level
    credibility: Credibility
    entity: Optional[str] = Field(None, max_length=80)
    attribute: Optional[Attribute] = None
    quote: str = Field("", max_length=600)
    hit_document_id: Optional[str] = Field(None, max_length=64)
    analyst_notes: str = Field("", max_length=600)


class GenerateReportArgs(Args):
    run_id: str = Field(..., max_length=64)
    sections: Optional[list[str]] = Field(None, max_length=12)
