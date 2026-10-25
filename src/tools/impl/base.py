from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class ToolError(Exception):
    """Expected, model-recoverable failure. Converted to a structured error by the dispatcher."""

    def __init__(self, code: str, message: str, field_name: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field_name


@dataclass
class ToolContext:
    state: Any
    corpus: Any
    settings: Any
    log: Any = None
    report_builder: Optional[Callable[[list[str] | None], dict]] = None
    extra: dict = field(default_factory=dict)
