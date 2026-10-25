"""Research Planner: Scope -> validated ResearchPlan (+ a naive baseline for comparison)."""
from __future__ import annotations

import json

from src.prompts import planner as P
from src.schemas.plan import (EvidenceType, Objective, Priority, ResearchPlan, ResearchToolName, Scope,
                              SubQuestion, validate_plan)


def _fallback_plan(scope: Scope) -> ResearchPlan:
    S, R, C, M = (ResearchToolName.search_information, ResearchToolName.retrieve_document,
                  ResearchToolName.calculate_metric, ResearchToolName.compare_companies)
    seg = scope.segment if "UNSPECIFIED" not in scope.segment else "the category"

    def q(i, t, et, tools, done):
        return SubQuestion(id=i, text=t, evidence_type=et, candidate_tools=tools, priority=Priority.high, done_when=done)

    return ResearchPlan(objectives=[
        Objective(id="O1", title="Identify the vendors and their positioning", sub_questions=[
            q("Q1.1", f"Which vendors are named in the sources as active in {seg}?", EvidenceType.company_profile, [S], "A list of vendors with source ids"),
            q("Q1.2", "Which customer segment does each identified vendor state it targets?", EvidenceType.positioning, [S, R], "Each vendor has a stated segment or is marked unknown")]),
        Objective(id="O2", title="Compare published pricing", sub_questions=[
            q("Q2.1", "What entry-tier price per seat per month does each vendor publish?", EvidenceType.pricing, [S, R], "Price or 'not published' per vendor"),
            q("Q2.2", "Which vendors publish enterprise pricing or seat minimums, and what are they?", EvidenceType.pricing, [S, R, M], "Enterprise price/minimum or explicit gap per vendor")]),
        Objective(id="O3", title="Establish market size and direction", sub_questions=[
            q("Q3.1", "What market size figures do analyst or press sources state, for which year?", EvidenceType.market_size, [S, R], "Each figure with source and year"),
            q("Q3.2", "What growth rate is implied by the stated market size figures?", EvidenceType.trend, [S, C], "A computed growth rate or a stated gap")]),
    ])


def make_plan(client, scope: Scope, clarifications: dict | None = None, log=None) -> tuple[ResearchPlan, dict | None]:
    payload = {"scope": scope.model_dump(mode="json"), "clarifications": clarifications or {}}
    msgs = [{"role": "system", "content": P.SYSTEM},
            {"role": "user", "content": "Scope object (data):\n" + json.dumps(payload, indent=2)}]
    plan, defect = client.structured("planner", msgs, ResearchPlan, "research_plan",
                                     fallback=lambda: _fallback_plan(scope),
                                     validator=lambda p: validate_plan(p, scope))
    problems = validate_plan(plan, scope)
    if log:
        log.event("plan", "planner", prompt_version=P.VERSION, objectives=len(plan.objectives),
                  questions=len(plan.questions()), validator_problems=problems, defect=defect)
    return plan, defect


def naive_plan(client, topic: str) -> str:
    """Baseline for Task 04's comparison: a single unconstrained prompt."""
    return client.text("planner", "You are a helpful assistant.", P.NAIVE.format(topic=topic))
