from __future__ import annotations

import threading

from .errors import BrokerRequestError, SessionNotFound
from .model import SessionRecord


class SessionRegistry:
    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._lock = threading.RLock()

    def add(self, record: SessionRecord) -> None:
        with self._lock:
            if record.session_id in self._records:
                raise BrokerRequestError(f"session already exists: {record.session_id}")
            self._records[record.session_id] = record

    def get(self, session_id: str) -> SessionRecord:
        with self._lock:
            try:
                return self._records[session_id]
            except KeyError as error:
                raise SessionNotFound(f"session does not exist: {session_id}") from error

    def replace(self, record: SessionRecord) -> None:
        with self._lock:
            if record.session_id not in self._records:
                raise SessionNotFound(f"session does not exist: {record.session_id}")
            self._records[record.session_id] = record

    def remove(self, session_id: str) -> SessionRecord:
        with self._lock:
            try:
                return self._records.pop(session_id)
            except KeyError as error:
                raise SessionNotFound(f"session does not exist: {session_id}") from error

    def list(self) -> tuple[SessionRecord, ...]:
        with self._lock:
            return tuple(sorted(self._records.values(), key=lambda record: record.created_at))
