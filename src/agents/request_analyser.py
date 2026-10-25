"""Request Analyser: raw request -> Scope with surfaced ambiguity (never silently invented)."""
from __future__ import annotations

import re

from src.prompts import request_analyser as P
from src.schemas.plan import Ambiguity, Complexity, Resolution, Scope
from src.tools.impl.corpus import scan_injection

MAX_REQUEST_CHARS = 2000
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class InputError(ValueError):
    pass


def sanitise_request(text: str) -> str:
    if not isinstance(text, str):
        raise InputError("Request must be text.")
    text = _CTRL.sub("", text).strip()
    if len(text) < 8:
        raise InputError("Request is too short to scope (min 8 characters).")
    if len(text) > MAX_REQUEST_CHARS:
        raise InputError(f"Request is too long ({len(text)} chars, max {MAX_REQUEST_CHARS}).")
    return text.replace("</client_request>", "")  # cannot close the data delimiter


def _fallback(text: str) -> Scope:
    return Scope(entity_type="UNSPECIFIED (see ambiguities)", segment="UNSPECIFIED (see ambiguities)",
                 geography="UNSPECIFIED (see ambiguities)", time_horizon="UNSPECIFIED (see ambiguities)",
                 deliverable_type="market intelligence brief", complexity=Complexity.standard,
                 normalised_objective=f"Research request (scope analysis failed, needs clarification): {text[:300]}",
                 ambiguities=[Ambiguity(dimension="scope", issue="Automatic scope analysis failed validation.",
                                        resolution=Resolution.clarify,
                                        clarification_question="Please restate the market, segment, geography and horizon.",
                                        default_assumption="Global market, all segments, current year.")])


def analyse_request(client, text: str, log=None) -> Scope:
    text = sanitise_request(text)
    flags = scan_injection(text)
    msgs = [{"role": "system", "content": P.SYSTEM},
            {"role": "user", "content": f"<client_request>\n{text}\n</client_request>"}]
    scope, defect = client.structured("request_analyser", msgs, Scope, "scope", fallback=lambda: _fallback(text))
    if flags:
        scope.injection_suspected = True
    if log:
        log.event("scope", "request_analyser", prompt_version=P.VERSION, injection_patterns=flags,
                  ambiguities=len(scope.ambiguities), complexity=scope.complexity.value, defect=defect)
        if scope.injection_suspected:
            log.event("request_injection_flagged", "request_analyser", "WARNING", lines=flags,
                      note="Controls are enforced in code; the request cannot disable evidence rules or approval.")
    return scope


def apply_clarifications(scope: Scope, answers: dict[str, str]) -> Scope:
    """Fold reviewer/client answers into the scope; unanswered 'clarify' items become recorded assumptions."""
    for amb in scope.ambiguities:
        ans = (answers.get(amb.dimension) or "").strip()
        if ans:
            amb.default_assumption = f"CLIENT ANSWER: {ans}"
            amb.resolution = Resolution.assume
            if hasattr(scope, amb.dimension) and amb.dimension not in ("ambiguities", "complexity"):
                setattr(scope, amb.dimension, ans[:120])
    return scope
