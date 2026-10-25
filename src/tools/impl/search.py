from src.schemas.tools import SearchArgs
from src.tools.impl.base import ToolContext


def search_information(args: SearchArgs, ctx: ToolContext) -> dict:
    hits = ctx.corpus.search(args.query, args.source_type.value, args.max_results, args.recency_window.value)
    # Always a well-formed list - empty is a valid answer, never a prose apology.
    return {"query": args.query, "hit_count": len(hits), "hits": hits}
