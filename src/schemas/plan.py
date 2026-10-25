"""Scope + research plan schemas and the in-code plan validator (Task 03/04)."""
from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Complexity(str, Enum):
    simple = "simple"
    standard = "standard"
    complex = "complex"


class Resolution(str, Enum):
    clarify = "clarify"   # ask the client
    assume = "assume"     # proceed with a recorded default


class Ambiguity(Strict):
    dimension: str = Field(..., max_length=40, description="e.g. geography, segment, time_horizon")
    issue: str = Field(..., max_length=300)
    resolution: Resolution
    clarification_question: str = Field(..., max_length=300)
    default_assumption: str = Field(..., max_length=300)


class Scope(Strict):
    entity_type: str = Field(..., max_length=120)
    segment: str = Field(..., max_length=120)
    geography: str = Field(..., max_length=120)
    time_horizon: str = Field(..., max_length=120)
    deliverable_type: str = Field(..., max_length=120)
    complexity: Complexity
    normalised_objective: str = Field(..., min_length=10, max_length=600)
    named_entities: list[str] = Field(default_factory=list, max_length=15)
    ambiguities: list[Ambiguity] = Field(default_factory=list, max_length=10)
    injection_suspected: bool = False


class EvidenceType(str, Enum):
    pricing = "pricing"
    product_capability = "product_capability"
    market_size = "market_size"
    positioning = "positioning"
    customer_evidence = "customer_evidence"
    trend = "trend"
    regulatory = "regulatory"
    company_profile = "company_profile"


class ResearchToolName(str, Enum):
    search_information = "search_information"
    retrieve_document = "retrieve_document"
    calculate_metric = "calculate_metric"
    compare_companies = "compare_companies"


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SubQuestion(Strict):
    id: str = Field(..., pattern=r"^Q\d+\.\d+$")
    text: str = Field(..., min_length=15, max_length=300)
    evidence_type: EvidenceType
    candidate_tools: list[ResearchToolName] = Field(..., min_length=1, max_length=4)
    priority: Priority
    done_when: str = Field(..., min_length=5, max_length=200, description="Observable stopping condition")


class Objective(Strict):
    id: str = Field(..., pattern=r"^O\d+$")
    title: str = Field(..., min_length=5, max_length=160)
    sub_questions: list[SubQuestion] = Field(..., min_length=1, max_length=5)


class ResearchPlan(Strict):
    objectives: list[Objective] = Field(..., min_length=1, max_length=6)

    def questions(self) -> list[SubQuestion]:
        return [q for o in self.objectives for q in o.sub_questions]


_VAGUE = re.compile(r"^(analy[sz]e|understand|explore|look at|research|investigate|describe)\b.*\b(market|landscape|space|industry)\b\.?$", re.I)


def validate_plan(plan: ResearchPlan, scope: Scope | None = None,
                  available_tools: set[str] | None = None) -> list[str]:
    """Deterministic plan checks. Returns a list of problems (empty == valid)."""
    errs: list[str] = []
    available_tools = available_tools or {t.value for t in ResearchToolName}
    simple = scope is not None and scope.complexity == Complexity.simple
    lo, hi = (1, 2) if simple else (3, 6)
    if not lo <= len(plan.objectives) <= hi:
        errs.append(f"plan must have {lo}-{hi} objectives for a {'simple' if simple else 'standard/complex'} request, got {len(plan.objectives)}")
    seen_text: set[str] = set()
    seen_ids: set[str] = set()
    for o in plan.objectives:
        min_q = 1 if simple else 2
        if not min_q <= len(o.sub_questions) <= 5:
            errs.append(f"{o.id} must have {min_q}-5 sub-questions")
        for q in o.sub_questions:
            if not q.id.startswith(f"Q{o.id[1:]}."):
                errs.append(f"{q.id} id must be prefixed by its objective number ({o.id})")
            if q.id in seen_ids:
                errs.append(f"duplicate question id {q.id}")
            seen_ids.add(q.id)
            norm = re.sub(r"\W+", " ", q.text.lower()).strip()
            if norm in seen_text:
                errs.append(f"duplicate question text at {q.id}")
            seen_text.add(norm)
            if not any(t.value in available_tools for t in q.candidate_tools):
                errs.append(f"{q.id} maps to no available tool")
            if _VAGUE.match(q.text.strip()) or len(q.text.split()) < 6:
                errs.append(f"{q.id} is unbounded/vague - rewrite it so an analyst would know when they were finished: '{q.text}'")
    return errs
