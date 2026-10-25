"""Token + cost accounting per call, attributed to stage and run."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class CallRecord:
    run_id: str
    stage: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_s: float
    priced: bool  # False => fallback (pessimistic) price used because the model was unknown
    ts: str


class UsageTracker:
    def __init__(self, settings, run_id: str):
        self.settings = settings
        self.run_id = run_id
        self.records: list[CallRecord] = []

    def record(self, stage: str, model: str, prompt_tokens: int, completion_tokens: int, latency_s: float) -> CallRecord:
        (pin, pout), priced = self.settings.price_for(model)
        cost = prompt_tokens / 1e6 * pin + completion_tokens / 1e6 * pout
        rec = CallRecord(self.run_id, stage, model, prompt_tokens, completion_tokens, round(cost, 6),
                         round(latency_s, 3), priced, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.records.append(rec)
        return rec

    @property
    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self.records), 6)

    @property
    def total_tokens(self) -> int:
        return sum(r.prompt_tokens + r.completion_tokens for r in self.records)

    def by_stage(self) -> dict:
        out: dict = {}
        for r in self.records:
            s = out.setdefault(r.stage, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                         "cost_usd": 0.0, "latency_s": 0.0, "model": r.model})
            s["calls"] += 1
            s["prompt_tokens"] += r.prompt_tokens
            s["completion_tokens"] += r.completion_tokens
            s["cost_usd"] = round(s["cost_usd"] + r.cost_usd, 6)
            s["latency_s"] = round(s["latency_s"] + r.latency_s, 3)
        return out

    def summary(self) -> dict:
        return {
            "run_id": self.run_id, "calls": len(self.records), "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost, "budget_usd": self.settings.budget_usd,
            "budget_respected": self.total_cost <= self.settings.budget_usd * 1.0001 or None,
            "unpriced_models": sorted({r.model for r in self.records if not r.priced}),
            "by_stage": self.by_stage(),
        }

    def to_list(self) -> list[dict]:
        return [asdict(r) for r in self.records]

    def load(self, rows: list[dict]) -> None:
        self.records = [CallRecord(**r) for r in rows]
