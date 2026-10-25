"""Comparison Agent: deterministic matrix from the evidence store via the compare_companies tool."""
from __future__ import annotations

from src.schemas.evidence import Attribute

MATRIX_ATTRIBUTES = [Attribute.entry_price, Attribute.enterprise_price, Attribute.free_tier, Attribute.seat_minimum,
                     Attribute.ai_capabilities, Attribute.integrations, Attribute.deployment_options,
                     Attribute.data_residency, Attribute.target_segment]


def build_matrix(dispatcher, state, log=None) -> dict:
    ents: dict[str, int] = {}
    for e in state.evidence.values():
        if e.entity and e.entity.strip().casefold() not in {"market", "category", "industry"}:
            key = e.entity.strip()
            ents[key] = ents.get(key, 0) + 1
    for name in (state.scope.named_entities if state.scope else []):
        ents.setdefault(name, 0)
    entities = [k for k, _ in sorted(ents.items(), key=lambda kv: -kv[1])][:10]
    if not entities:
        matrix = {"entities": [], "attributes": [a.value for a in MATRIX_ATTRIBUTES], "cells": {}, "not_established_count": 0}
    else:
        env = dispatcher.dispatch("comparison", "compare_companies",
                                  {"entities": entities, "attributes": [a.value for a in MATRIX_ATTRIBUTES]})
        matrix = env["data"] if env["ok"] else {"entities": entities, "attributes": [], "cells": {},
                                                 "error": env["error"], "not_established_count": 0}
    state.matrix = matrix
    if log:
        log.event("matrix", "comparison", entities=len(matrix["entities"]),
                  not_established=matrix.get("not_established_count", 0))
    return matrix
