from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .buffer import BufferRead


class TerminalProcess(Protocol):
    """Minimal terminal capability owned by one session worker."""

    backend_name: str

    @property
    def running(self) -> bool: ...

    @property
    def output_cursor(self) -> int: ...

    def start(
        self,
        arguments: Sequence[str],
        *,
        cwd: str | Path | None = None,
        environment: dict[str, str] | None = None,
        columns: int = 120,
        rows: int = 30,
    ) -> None: ...

    def write(self, data: bytes) -> None: ...

    def read(self, cursor: int) -> BufferRead: ...

    def wait_for_data(self, cursor: int, timeout: float | None = None) -> BufferRead: ...

    def resize(self, columns: int, rows: int) -> None: ...

    def wait(self, timeout: float | None = None) -> int | None: ...

    def terminate(self, exit_code: int = 1) -> None: ...

    def close(self) -> None: ...
