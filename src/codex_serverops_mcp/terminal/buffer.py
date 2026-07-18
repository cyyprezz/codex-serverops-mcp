from __future__ import annotations

from dataclasses import dataclass
from threading import Condition
from time import monotonic


@dataclass(frozen=True, slots=True)
class BufferRead:
    data: bytes
    next_cursor: int
    dropped_before_cursor: bool


class TerminalRingBuffer:
    """Thread-safe absolute-cursor byte ring buffer."""

    def __init__(self, max_bytes: int = 1_048_576) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes
        self._data = bytearray()
        self._start = 0
        self._condition = Condition()
        self._closed = False

    @property
    def end_cursor(self) -> int:
        with self._condition:
            return self._start + len(self._data)

    @property
    def start_cursor(self) -> int:
        with self._condition:
            return self._start

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self._condition:
            self._data.extend(data)
            overflow = len(self._data) - self._max_bytes
            if overflow > 0:
                del self._data[:overflow]
                self._start += overflow
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def read(self, cursor: int) -> BufferRead:
        with self._condition:
            return self._read_locked(cursor)

    def wait_for_data(self, cursor: int, timeout: float | None) -> BufferRead:
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while not self._closed and cursor >= self._start + len(self._data):
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._read_locked(cursor)

    def _read_locked(self, cursor: int) -> BufferRead:
        dropped = cursor < self._start
        effective = max(cursor, self._start)
        offset = min(effective - self._start, len(self._data))
        data = bytes(self._data[offset:])
        return BufferRead(data, self._start + len(self._data), dropped)

