"""save_research: the strongest structural defence against fabricated citations.

A record is rejected unless its source_ref resolves to a real, successful, prior tool result,
and unless any quote it carries actually occurs in that result's text.
"""
from __future__ import annotations

import re
from datetime import date

from src.schemas.evidence import ClaimType, Credibility, EvidenceRecord, Level, SourceKind
from src.schemas.tools import SaveArgs
from src.tools.impl.base import ToolContext, ToolError

_NUM = re.compile(r"\$?\s?\d[\d,]*(?:\.\d+)?\s?(?:%|bn|billion|m\b|million|k\b|seats?)?", re.I)
_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 0}


def _norm(t: str) -> str:
    t = t.lower().replace("…", " ").replace("’", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[*_`>#|]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM.findall(text):
        s = re.sub(r"[\s,$]", "", m.lower())
        s = s.replace("billion", "bn").replace("million", "m").rstrip("s")
        if re.search(r"\d", s) and not re.fullmatch(r"(19|20)\d\d", s):  # ignore bare years
            out.add(s)
    return out


_YEAR = re.compile(r"\b(?:19|20)\d\d\b")


def years(text: str) -> set[str]:
    return set(_YEAR.findall(text))


def _date(e) -> str:
    return (e.recency or "")[:10]


def _superseded(a, b) -> bool:
    try:
        da, db = date.fromisoformat(_date(a)), date.fromisoformat(_date(b))
    except ValueError:
        return False
    return abs((da - db).days) >= 730


def _recency(ctx: ToolContext, d: str | None) -> str:
    if not d:
        return "unknown"
    try:
        age = (date.fromisoformat(ctx.settings.corpus_reference_date) - date.fromisoformat(d)).days / 365.25
    except ValueError:
        return "unknown"
    return f"{d} ({'<1y' if age < 1 else '1-3y' if age < 3 else '3-5y' if age < 5 else '>5y'})"


def _resolve_source(args: SaveArgs, src: dict, ctx: ToolContext):
    tool, data = src["tool"], src["data"]
    if tool == "calculate_metric":
        return SourceKind.calculation, {"operation": data["operation"], "formula": data["formula"],
                                        "inputs": data["inputs"], "result": data["result"]}, str(data), None
    if tool == "retrieve_document":
        detail = {k: data.get(k) for k in ("document_id", "title", "date", "source_type", "vendor", "section")}
        return SourceKind.retrieved_document, detail, data["text"], data.get("date")
    if tool == "search_information":
        hits = data.get("hits", [])
        if not hits:
            raise ToolError("unresolvable_source_ref", f"{args.source_ref} returned no hits; nothing can be cited from it")
        hit = next((h for h in hits if h["document_id"] == args.hit_document_id), None) if args.hit_document_id else hits[0]
        if hit is None:
            raise ToolError("unresolvable_source_ref",
                            f"hit_document_id '{args.hit_document_id}' is not among the hits of {args.source_ref}", "hit_document_id")
        same_doc = [h for h in hits if h["document_id"] == hit["document_id"]]
        match = next((h for h in same_doc if args.quote and _norm(args.quote) in _norm(h["snippet"])), hit)
        detail = {k: match.get(k) for k in ("document_id", "title", "date", "source_type", "vendor", "section")}
        return SourceKind.search_result, detail, "\n".join(h["snippet"] for h in same_doc), match.get("date")
    raise ToolError("invalid_source_kind", f"{tool} results cannot be cited as evidence", "source_ref")


def save_research(args: SaveArgs, ctx: ToolContext) -> dict:
    st = ctx.state
    if st.question(args.question_id) is None:
        raise ToolError("unknown_question", f"question_id '{args.question_id}' is not in the plan", "question_id")
    src = st.tool_results.get(args.source_ref)
    if not src or not src.get("ok"):
        raise ToolError("unresolvable_source_ref",
                        f"source_ref '{args.source_ref}' does not resolve to a successful prior tool result", "source_ref")
    kind, detail, text, d = _resolve_source(args, src, ctx)
    if args.claim_type == ClaimType.fact and kind != SourceKind.calculation and not args.quote.strip():
        raise ToolError("missing_quote", "claims typed 'fact' must carry a verbatim quote from the source", "quote")
    if args.quote.strip() and _norm(args.quote) not in _norm(text):
        raise ToolError("quote_not_in_source", "the quote does not occur in the cited tool result - possible fabrication", "quote")

    doc_id = detail.get("document_id")
    for e in st.evidence.values():  # same claim from the same document: link, don't duplicate
        if doc_id and e.source_detail.get("document_id") == doc_id and _norm(e.claim) == _norm(args.claim):
            if args.question_id != e.question_id and args.question_id not in e.also_supports:
                e.also_supports.append(args.question_id)
            return {"evidence_id": e.evidence_id, "corroboration": e.corroboration,
                    "conflicts_with": e.conflicts_with, "uncertainty_record": None, "deduplicated": True}
    rec = EvidenceRecord(
        evidence_id=st.next_evidence_id(), question_id=args.question_id, claim=args.claim,
        claim_type=args.claim_type, entity=(args.entity or None), attribute=args.attribute,
        source_ref=args.source_ref, source_kind=kind, source_detail=detail, quote=args.quote,
        credibility=args.credibility, recency=_recency(ctx, d), confidence=args.confidence,
        analyst_notes=args.analyst_notes,
    )
    uncertainty_id = _link(st, rec, ctx)
    st.evidence[rec.evidence_id] = rec
    return {"evidence_id": rec.evidence_id, "corroboration": rec.corroboration,
            "conflicts_with": rec.conflicts_with, "uncertainty_record": uncertainty_id}


def _link(st, rec: EvidenceRecord, ctx: ToolContext) -> str | None:
    """Corroborate agreeing records; turn disagreements into an uncertainty record (never pick a winner)."""
    if rec.attribute is None or rec.claim_type == ClaimType.uncertainty or not rec.entity:
        return None
    mine = numbers(rec.claim)
    created = None
    for other in list(st.evidence.values()):
        if (other.claim_type == ClaimType.uncertainty or other.attribute != rec.attribute
                or not other.entity or other.entity.casefold() != rec.entity.casefold()):
            continue
        if other.source_detail.get("document_id") and other.source_detail.get("document_id") == rec.source_detail.get("document_id"):
            continue  # same document is not independent corroboration
        theirs = numbers(other.claim)
        if not mine or not theirs:
            continue
        ya, yb = years(rec.claim), years(other.claim)
        if ya and yb and not (ya & yb):
            continue  # figures for different years are not comparable (e.g. 2025 actual vs 2028 projection)
        if mine & theirs:
            rec.corroboration.append(other.evidence_id)
            if rec.evidence_id not in other.corroboration:
                other.corroboration.append(rec.evidence_id)
        elif _superseded(rec, other):
            # Explicit, mechanical resolution rule: a source >= 2 years older than another on the same
            # attribute is superseded. The older value is RECORDED (not deleted) and down-weighted.
            old, new = (other, rec) if _date(other) < _date(rec) else (rec, other)
            old.confidence = Level.low
            old.analyst_notes = (old.analyst_notes + f" [superseded by {new.evidence_id}: newer source on same attribute]")[:600]
            if ctx.log:
                ctx.log.event("superseded", "evidence_analyst", old=old.evidence_id, new=new.evidence_id)
        else:
            rec.conflicts_with.append(other.evidence_id)
            other.conflicts_with.append(rec.evidence_id)
            rec.confidence = other.confidence = Level.low
            existing = next((u for u in st.evidence.values() if u.claim_type == ClaimType.uncertainty
                             and u.entity and u.entity.casefold() == rec.entity.casefold()
                             and u.attribute == rec.attribute), None)
            if existing:
                if rec.evidence_id not in existing.corroboration:
                    existing.corroboration.append(rec.evidence_id)
                    existing.analyst_notes = (existing.analyst_notes + f" Further conflicting source: {rec.evidence_id}.")[:600]
                continue
            t_other = other.source_detail.get("title", other.source_ref)
            t_mine = rec.source_detail.get("title", rec.source_ref)
            uid = f"E{int(rec.evidence_id[1:]) + 1:03d}"
            while uid in st.evidence or uid == rec.evidence_id:
                uid = f"E{int(uid[1:]) + 1:03d}"
            cred = min([rec.credibility, other.credibility], key=lambda c: _RANK[c.value])
            unc = EvidenceRecord(
                evidence_id=uid, question_id=rec.question_id,
                claim=(f"Sources disagree on {rec.attribute.value.replace('_', ' ')} for {rec.entity}: "
                       f"'{t_other}' states \"{other.claim}\" [{other.evidence_id}], while '{t_mine}' states "
                       f"\"{rec.claim}\" [{rec.evidence_id}]. Not resolved by the system.")[:690],
                claim_type=ClaimType.uncertainty, entity=rec.entity, attribute=rec.attribute,
                source_ref=rec.source_ref, source_kind=rec.source_kind, source_detail=rec.source_detail,
                credibility=Credibility(cred.value), recency=rec.recency,
                corroboration=[other.evidence_id, rec.evidence_id], confidence=Level.low,
                analyst_notes="Generated by the conflict detector: numeric values disagree across independent sources.",
                created_by_stage="conflict_detector")
            st.evidence[uid] = unc
            created = uid
            if ctx.log:
                ctx.log.event("conflict_detected", "evidence_analyst", "WARNING", uncertainty_id=uid,
                              records=[other.evidence_id, rec.evidence_id], entity=rec.entity, attribute=rec.attribute.value)
    return created
