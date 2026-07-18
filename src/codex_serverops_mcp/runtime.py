from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_serverops_mcp.config import default_config_path
from codex_serverops_mcp.identifiers import validate_session_id
from codex_serverops_mcp.ipc.security import secure_path_for_current_user

MAX_RUNTIME_JSON_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class StaleRuntimeCleanup:
    broker_status_removed: bool
    dead_worker_statuses_removed: tuple[str, ...]
    live_worker_statuses_preserved: tuple[str, ...]
    unreadable_worker_statuses_preserved: tuple[str, ...]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate runtime status field: {key}")
        result[key] = value
    return result


def default_runtime_path() -> Path:
    return default_config_path().parent / "runtime"


class RuntimeDirectory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or default_runtime_path()).resolve()
        self.workers_path = self.path / "workers"
        self.broker_status_path = self.path / "broker.json"

    def prepare(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        secure_path_for_current_user(str(self.path), directory=True)
        self.workers_path.mkdir(parents=True, exist_ok=True)
        secure_path_for_current_user(str(self.workers_path), directory=True)

    def worker_status_path(self, session_id: str) -> Path:
        validate_session_id(session_id)
        return self.workers_path / f"{session_id}.json"

    def write_json(self, path: Path, document: dict[str, object]) -> None:
        content = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(content) > MAX_RUNTIME_JSON_BYTES:
            raise ValueError("runtime status exceeds its size limit")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            secure_path_for_current_user(str(temporary))
            os.replace(temporary, path)
            secure_path_for_current_user(str(path))
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def read_json(self, path: Path) -> dict[str, object]:
        content = path.read_bytes()
        if not content or len(content) > MAX_RUNTIME_JSON_BYTES:
            raise ValueError("runtime status has an invalid size")
        document = json.loads(content.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(document, dict):
            raise ValueError("runtime status must be an object")
        return document

    def clean_stale_statuses(
        self,
        *,
        process_is_alive: Callable[[int], bool],
    ) -> StaleRuntimeCleanup:
        """Remove only status records whose owning process is certainly gone.

        This must be called only after the caller owns the per-user broker pipe.
        A live or unreadable worker record is deliberately preserved.
        """
        broker_removed = self.broker_status_path.exists()
        self.broker_status_path.unlink(missing_ok=True)
        dead: list[str] = []
        live: list[str] = []
        unreadable: list[str] = []
        for path in sorted(self.workers_path.glob("sess-*.json")):
            try:
                document = self.read_json(path)
                pid = document["pid"]
                if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
                    raise ValueError("worker status has an invalid PID")
            except (OSError, KeyError, ValueError):
                unreadable.append(path.name)
                continue
            if process_is_alive(pid):
                live.append(path.name)
                continue
            path.unlink(missing_ok=True)
            dead.append(path.name)
        return StaleRuntimeCleanup(
            broker_status_removed=broker_removed,
            dead_worker_statuses_removed=tuple(dead),
            live_worker_statuses_preserved=tuple(live),
            unreadable_worker_statuses_preserved=tuple(unreadable),
        )
