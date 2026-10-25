"""Central, run-scoped structured logging. Every stage writes here.

Events go to: console (std logging), runs/<run_id>/run_log.jsonl, and an in-memory list
that the Streamlit UI renders live. All text is scrubbed of anything key-shaped.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.config import scrub

_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    _configured = True


class RunLogger:
    def __init__(self, run_id: str, runs_dir: Path, level: str = "INFO",
                 on_event: Callable[[dict], None] | None = None):
        configure_logging(level)
        self.run_id = run_id
        self.dir = Path(runs_dir) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "run_log.jsonl"
        self.events: list[dict] = []
        self.on_event = on_event
        self._log = logging.getLogger(f"marketmind.{run_id}")
        fh = logging.FileHandler(self.dir / "console.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
        if not any(isinstance(h, logging.FileHandler) for h in self._log.handlers):
            self._log.addHandler(fh)

    def event(self, kind: str, stage: str = "", level: str = "INFO", **data: Any) -> dict:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id, "stage": stage, "kind": kind, "level": level,
            **data,
        }
        line = scrub(json.dumps(rec, default=str, ensure_ascii=False))
        rec = json.loads(line)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.events.append(rec)
        msg = f"[{stage or '-'}] {kind}: " + scrub(json.dumps({k: v for k, v in data.items()}, default=str))[:400]
        getattr(self._log, level.lower(), self._log.info)(msg)
        if self.on_event:
            try:
                self.on_event(rec)
            except Exception:  # UI callbacks must never break the run
                pass
        return rec


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.perf_counter() - self.t0
