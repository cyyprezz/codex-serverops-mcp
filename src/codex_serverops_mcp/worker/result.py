from __future__ import annotations

from dataclasses import dataclass

from .state import SessionState


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    output: str
    exit_code: int
    cwd: str
    truncated: bool
    duration_ms: int


@dataclass(frozen=True, slots=True)
class InteractiveStatus:
    state: SessionState
    running: bool
    output_cursor: int


@dataclass(frozen=True, slots=True)
class InteractiveRead:
    output: str
    next_cursor: int
    dropped_before_cursor: bool
    state: SessionState
