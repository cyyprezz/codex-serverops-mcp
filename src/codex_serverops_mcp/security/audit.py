from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from codex_serverops_mcp.config import default_config_path

from .locking import AuditFileLock
from .redaction import redact_preview

AUDIT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AuditWriteResult:
    logged: bool
    command_redacted: bool
    command_preview_truncated: bool


def default_audit_path(*, local_app_data: str | None = None) -> Path:
    return default_config_path(local_app_data).parent / "audit"


class AuditLogger:
    def __init__(
        self,
        root: Path | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = (root or default_audit_path()).resolve()
        self._now = now or (lambda: datetime.now(UTC))

    def record(
        self,
        *,
        tool: str,
        action: str,
        result: Mapping[str, object] | None,
        duration_ms: int,
        error_status: str | None = None,
        profile: str | None = None,
        session_id: str | None = None,
        ssh_user: str | None = None,
        effective_user: str | None = None,
        command: str | None = None,
    ) -> AuditWriteResult:
        timestamp = self._now().astimezone(UTC)
        response = result or {}
        preview = redact_preview(command) if command is not None else None
        event: dict[str, object] = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "profile": _text(response.get("profile_name")) or profile,
            "session_id": _text(response.get("session_id")) or session_id,
            "ssh_user": _text(response.get("ssh_user")) or ssh_user,
            "effective_user": _text(response.get("effective_user")) or effective_user,
            "tool": tool,
            "action": action,
            "result_status": error_status or _text(response.get("status")) or "completed",
            "exit_code": _integer(response.get("exit_code")),
            "duration_ms": max(0, duration_ms),
            "output_truncated": response.get("truncated") is True,
            "elevated": response.get("elevated") is True,
            "command_preview": None if preview is None else preview.text,
            "command_sha256": (
                None
                if command is None
                else hashlib.sha256(command.encode("utf-8")).hexdigest()
            ),
            "command_redacted": False if preview is None else preview.redacted,
            "command_preview_truncated": False if preview is None else preview.truncated,
        }
        self._append(timestamp.date().isoformat(), event)
        return AuditWriteResult(
            logged=True,
            command_redacted=False if preview is None else preview.redacted,
            command_preview_truncated=False if preview is None else preview.truncated,
        )

    def _append(self, day: str, event: Mapping[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _secure_for_current_user(self.root, directory=True)
        path = self.root / f"{day}.jsonl"
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with AuditFileLock(self.root / ".audit.lock"):
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            _secure_for_current_user(path, directory=False)


def _secure_for_current_user(path: Path, *, directory: bool) -> None:
    if os.name != "nt":  # pragma: no cover - product runtime is Windows
        return
    from codex_serverops_mcp.ipc.security import secure_path_for_current_user

    secure_path_for_current_user(str(path), directory=directory)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
