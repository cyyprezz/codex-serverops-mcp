from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .audit import AuditLogger, AuditWriteResult
from .redaction import redact_preview


@dataclass(slots=True)
class ApplicationAudit:
    logger: AuditLogger | None

    def call(
        self,
        tool: str,
        action: str,
        operation: Callable[[], dict[str, object]],
        *,
        profile: str | None = None,
        session_id: str | None = None,
        command: str | None = None,
    ) -> dict[str, object]:
        if self.logger is None:
            return operation()
        started = time.monotonic()
        try:
            result = operation()
        except Exception as error:
            self._safe_record(
                tool=tool,
                action=action,
                result=None,
                duration_ms=_elapsed_ms(started),
                error_status=getattr(error, "code", "error"),
                profile=profile,
                session_id=session_id,
                command=command,
            )
            raise
        written = self._safe_record(
            tool=tool,
            action=action,
            result=result,
            duration_ms=_elapsed_ms(started),
            profile=profile,
            session_id=session_id,
            command=command,
        )
        return {
            **result,
            "audit": {
                "logged": written.logged,
                "command_redacted": written.command_redacted,
                "command_preview_truncated": written.command_preview_truncated,
            },
        }

    def _safe_record(self, **parameters: object) -> AuditWriteResult:
        try:
            return self.logger.record(**parameters)  # type: ignore[arg-type,union-attr]
        except Exception:
            command = parameters.get("command")
            preview = redact_preview(command) if isinstance(command, str) else None
            return AuditWriteResult(
                logged=False,
                command_redacted=False if preview is None else preview.redacted,
                command_preview_truncated=False if preview is None else preview.truncated,
            )


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))
