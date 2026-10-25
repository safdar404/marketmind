"""Save / resume a run and write the examiner-facing run artefacts to runs/<run_id>/."""
from __future__ import annotations

import json
from pathlib import Path

from src.state.research_state import ResearchState


def run_dir(runs_dir: Path, run_id: str) -> Path:
    d = Path(runs_dir) / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def save_state(state: ResearchState, runs_dir: Path, usage_summary: dict | None = None) -> Path:
    d = run_dir(runs_dir, state.run_id)
    _write(d / "state.json", state.model_dump(mode="json"))
    if state.plan:
        _write(d / "plan.json", {"scope": state.scope.model_dump(mode="json") if state.scope else None,
                                 "plan": state.plan.model_dump(mode="json"),
                                 "extra_questions": [q.model_dump(mode="json") for q in state.extra_questions],
                                 "question_status": {k: v.model_dump() for k, v in state.question_status.items()}})
    _write(d / "evidence.json", {"accepted": [e.model_dump(mode="json") for e in state.evidence.values()],
                                 "archived": [e.model_dump(mode="json") for e in state.archived_evidence.values()],
                                 "rejections": state.rejections})
    with (d / "tool_log.jsonl").open("w", encoding="utf-8") as f:
        for row in state.tool_history:
            f.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
    if state.qc:
        _write(d / "qc_verdict.json", state.qc)
    if state.report:
        _write(d / "report.json", state.report)
    if usage_summary:
        _write(d / "usage_summary.json", usage_summary)
    return d


def load_state(runs_dir: Path, run_id: str) -> ResearchState:
    p = Path(runs_dir) / run_id / "state.json"
    if not p.exists():
        raise FileNotFoundError(f"No saved state for run {run_id}")
    return ResearchState.model_validate_json(p.read_text(encoding="utf-8"))


def list_runs(runs_dir: Path) -> list[dict]:
    out = []
    for p in sorted(Path(runs_dir).glob("*/state.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"run_id": d["run_id"], "created_at": d.get("created_at"), "status": d.get("status"),
                        "stage": d.get("stage"), "request": (d.get("request") or "")[:90],
                        "evidence": len(d.get("evidence") or {})})
        except Exception:
            continue
    return out
