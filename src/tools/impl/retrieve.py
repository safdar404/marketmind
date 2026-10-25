from src.schemas.tools import RetrieveArgs
from src.tools.impl.base import ToolContext, ToolError

MAX_CHARS = 3500  # context budget per retrieved document


def retrieve_document(args: RetrieveArgs, ctx: ToolContext) -> dict:
    doc = ctx.corpus.get(args.document_id)
    if doc is None:  # exact id only: no fuzzy match, no paths, no URLs
        raise ToolError("unknown_document", f"document_id '{args.document_id}' is not in the index. "
                        "Use an id returned by search_information.", "document_id")
    text, section = doc.text, None
    if args.section:
        match = next((s for s in doc.sections if s.heading.lower() == args.section.lower()), None)
        if match is None:
            raise ToolError("unknown_section", f"section '{args.section}' not found. Available: "
                            + ", ".join(s.heading for s in doc.sections), "section")
        text, section = match.text, match.heading
    truncated = len(text) > MAX_CHARS
    return {"document_id": doc.id, "title": doc.title, "source_type": doc.source_type, "vendor": doc.vendor,
            "date": doc.date or None, "section": section, "sections": [s.heading for s in doc.sections],
            "text": text[:MAX_CHARS], "truncated": truncated,
            "recency_bucket": ctx.corpus.recency_bucket(doc), "credibility_hint": doc.credibility_hint or None}
