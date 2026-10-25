"""Entity x attribute matrix built ONLY from the evidence store. Gaps are explicit, never inferred."""
from src.schemas.tools import CompareArgs
from src.tools.impl.base import ToolContext

NOT_ESTABLISHED = "NOT_ESTABLISHED"


def _same_entity(a: str | None, b: str) -> bool:
    return bool(a) and a.strip().casefold() == b.strip().casefold()


def compare_companies(args: CompareArgs, ctx: ToolContext) -> dict:
    ev = [e for e in ctx.state.evidence.values()]
    cells, n_missing = {}, 0
    for ent in args.entities:
        row = {}
        for attr in args.attributes:
            recs = [e for e in ev if _same_entity(e.entity, ent) and e.attribute == attr]
            if not recs:
                row[attr.value] = {"status": NOT_ESTABLISHED, "values": []}
                n_missing += 1
                continue
            conflicting = any(e.conflicts_with for e in recs) or any(e.claim_type.value == "uncertainty" for e in recs)
            row[attr.value] = {
                "status": "conflicting" if conflicting else "established",
                "values": [{"evidence_id": e.evidence_id, "claim": e.claim, "claim_type": e.claim_type.value,
                            "confidence": e.confidence.value} for e in recs],
            }
        cells[ent] = row
    return {"entities": args.entities, "attributes": [a.value for a in args.attributes], "cells": cells,
            "not_established_count": n_missing}
