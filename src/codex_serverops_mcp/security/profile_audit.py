from __future__ import annotations

from dataclasses import dataclass

from codex_serverops_mcp.config import ServerProfile

from .audit import AuditLogger


@dataclass(frozen=True, slots=True)
class SetupAuditStatus:
    logged: bool

    @classmethod
    def from_result(cls, result: dict[str, object]) -> SetupAuditStatus:
        audit = result.get("audit")
        return cls(isinstance(audit, dict) and audit.get("logged") is True)

    @classmethod
    def combine(cls, *statuses: SetupAuditStatus) -> SetupAuditStatus:
        return cls(bool(statuses) and all(status.logged for status in statuses))

    def attach(self, result: dict[str, object]) -> dict[str, object]:
        previous = result.get("audit")
        previous_logged = (
            previous.get("logged") is True if isinstance(previous, dict) else True
        )
        return {**result, "audit": {"logged": self.logged and previous_logged}}


@dataclass(slots=True)
class ProfileAudit:
    logger: AuditLogger | None = None

    def record(
        self,
        action: str,
        profile_name: str,
        *,
        profile: ServerProfile | None = None,
        result_status: str = "completed",
    ) -> SetupAuditStatus:
        if self.logger is None:
            return SetupAuditStatus(False)
        result: dict[str, object] = {
            "profile_name": profile_name,
            "status": result_status,
        }
        if profile is not None:
            result.update(_safe_profile_capabilities(profile))
        try:
            written = self.logger.record(
                tool="server_profile_setup",
                action=action,
                result=result,
                duration_ms=0,
                profile=profile_name,
            )
        except Exception:
            return SetupAuditStatus(False)
        return SetupAuditStatus(written.logged)


def _safe_profile_capabilities(profile: ServerProfile) -> dict[str, object]:
    return {
        "connection_type": profile.connection_type.value,
        "authentication": profile.authentication.value,
        "environment": profile.environment,
        "terminal_enabled": profile.allow_terminal,
        "file_read_enabled": profile.allow_file_read,
        "file_write_enabled": profile.allow_file_write,
        "elevation_mode": profile.elevation_mode.value,
        "root_session_enabled": profile.allow_root_session,
    }
