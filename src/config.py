"""Validated settings object: models, temperatures, loop bounds and budget per run.

Every tunable lives here. Business logic never reads os.environ directly.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

STAGES = [
    "request_analyser", "planner", "researcher", "evidence_analyst",
    "synthesis", "quality_control", "report_generator",
]

DEFAULT_MODELS = {
    "request_analyser": "gpt-4o-mini",
    "planner": "gpt-4o",
    "researcher": "gpt-4o-mini",
    "evidence_analyst": "gpt-4o-mini",
    "synthesis": "gpt-4o",
    "quality_control": "gpt-4o",
    "report_generator": "gpt-4o-mini",
}

# Chosen from the Task 02 variance experiment (see docs/technical_documentation.md).
DEFAULT_TEMPERATURES = {
    "request_analyser": 0.0,
    "planner": 0.2,
    "researcher": 0.0,
    "evidence_analyst": 0.0,
    "synthesis": 0.3,
    "quality_control": 0.0,
    "report_generator": 0.2,
}

# USD per 1M tokens (input, output). INDICATIVE ONLY - verify on the official pricing page
# on the day you run, and override with MODEL_PRICING_JSON. Unknown models fall back to a
# deliberately pessimistic price so the budget ceiling errs on the safe side.
DEFAULT_PRICING = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
}
FALLBACK_PRICE = (5.00, 20.00)


class ConfigError(RuntimeError):
    """Raised at start-up when configuration is missing or invalid."""


def mask_key(key: str | None) -> str:
    if not key:
        return "<missing>"
    return key[:3] + "…" + key[-4:] if len(key) > 10 else "***"


_SECRET_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def scrub(text: str) -> str:
    """Remove anything that looks like an API key from text bound for logs/UI."""
    return _SECRET_RE.sub("sk-***redacted***", text)


@dataclass
class Settings:
    api_key: str = ""
    models: dict = field(default_factory=lambda: dict(DEFAULT_MODELS))
    temperatures: dict = field(default_factory=lambda: dict(DEFAULT_TEMPERATURES))
    pricing: dict = field(default_factory=lambda: dict(DEFAULT_PRICING))
    max_iterations: int = 40
    max_tool_calls: int = 60
    max_steps_per_question: int = 6
    budget_usd: float = 1.50
    max_repair_rounds: int = 2
    request_timeout_s: float = 60.0
    max_retries: int = 4
    tool_timeout_s: float = 10.0
    corpus_dir: Path = ROOT / "data" / "corpus"
    runs_dir: Path = ROOT / "runs"
    corpus_reference_date: str = "2026-06-30"
    log_level: str = "INFO"
    # Fault injection used by tests T-11 (never enabled by default).
    fault_injection: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ factory
    @classmethod
    def from_env(cls, require_key: bool = True, **overrides) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        s = cls()
        s.api_key = overrides.pop("api_key", None) or os.getenv("OPENAI_API_KEY", "")
        for stage in STAGES:
            s.models[stage] = os.getenv(f"MODEL_{stage.upper()}", s.models[stage])
            t = os.getenv(f"TEMP_{stage.upper()}")
            if t not in (None, ""):
                s.temperatures[stage] = float(t)
        ints = ["max_iterations", "max_tool_calls", "max_steps_per_question", "max_repair_rounds", "max_retries"]
        floats = ["budget_usd", "request_timeout_s", "tool_timeout_s"]
        for name in ints:
            v = os.getenv(name.upper())
            if v:
                setattr(s, name, int(v))
        for name in floats:
            v = os.getenv(name.upper())
            if v:
                setattr(s, name, float(v))
        if os.getenv("CORPUS_DIR"):
            s.corpus_dir = (ROOT / os.environ["CORPUS_DIR"]).resolve()
        if os.getenv("RUNS_DIR"):
            s.runs_dir = (ROOT / os.environ["RUNS_DIR"]).resolve()
        s.corpus_reference_date = os.getenv("CORPUS_REFERENCE_DATE", s.corpus_reference_date)
        s.log_level = os.getenv("LOG_LEVEL", s.log_level)
        pj = os.getenv("MODEL_PRICING_JSON", "").strip()
        if pj:
            try:
                s.pricing.update({k: tuple(v) for k, v in json.loads(pj).items()})
            except (ValueError, TypeError) as exc:
                raise ConfigError(f"MODEL_PRICING_JSON is not valid JSON: {exc}") from exc
        for k, v in overrides.items():
            if not hasattr(s, k):
                raise ConfigError(f"Unknown setting override: {k}")
            setattr(s, k, v)
        s.validate(require_key=require_key)
        return s

    def validate(self, require_key: bool = True) -> None:
        if require_key and not self.api_key:
            raise ConfigError("Missing required variable OPENAI_API_KEY (set it in .env or enter it in the app).")
        for name in ["max_iterations", "max_tool_calls", "max_steps_per_question", "max_retries"]:
            if getattr(self, name) < 1:
                raise ConfigError(f"{name.upper()} must be >= 1")
        if self.max_repair_rounds < 0:
            raise ConfigError("MAX_REPAIR_ROUNDS must be >= 0")
        if self.budget_usd <= 0:
            raise ConfigError("BUDGET_USD must be > 0")
        for stage in STAGES:
            if not self.models.get(stage):
                raise ConfigError(f"MODEL_{stage.upper()} is empty")
            if not 0.0 <= float(self.temperatures.get(stage, 0)) <= 2.0:
                raise ConfigError(f"TEMP_{stage.upper()} must be within [0, 2]")
        if not Path(self.corpus_dir).exists():
            raise ConfigError(f"CORPUS_DIR does not exist: {self.corpus_dir}")

    def price_for(self, model: str) -> tuple[tuple[float, float], bool]:
        if model in self.pricing:
            return tuple(self.pricing[model]), True
        # match dated snapshots such as gpt-4o-2024-08-06
        for base in sorted(self.pricing, key=len, reverse=True):
            if model.startswith(base + "-"):
                return tuple(self.pricing[base]), True
        return FALLBACK_PRICE, False

    def public_dict(self) -> dict:
        d = asdict(self)
        d["api_key"] = mask_key(self.api_key)
        d["corpus_dir"] = str(self.corpus_dir)
        d["runs_dir"] = str(self.runs_dir)
        return d


if __name__ == "__main__":  # smoke: python -m src.config
    try:
        cfg = Settings.from_env()
        print(json.dumps(cfg.public_dict(), indent=2, default=str))
    except ConfigError as e:
        raise SystemExit(f"[config] {e}")
