from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    profile_name: str
    worker_pid: int
    worker_pipe: str
    state: str
    created_at: float
    last_activity: float
    ssh_user: str | None = None
    effective_user: str | None = None
    root_session: bool = False
    parent_session_id: str | None = None

    def with_state(self, state: str, *, at: float) -> SessionRecord:
        return replace(self, state=state, last_activity=at)

    def with_open_status(
        self,
        *,
        ssh_user: str,
        effective_user: str,
        at: float,
    ) -> SessionRecord:
        return replace(
            self,
            state="ready",
            ssh_user=ssh_user,
            effective_user=effective_user,
            last_activity=at,
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "profile_name": self.profile_name,
            "worker_pid": self.worker_pid,
            "state": self.state,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "ssh_user": self.ssh_user,
            "effective_user": self.effective_user,
            "elevated": self.root_session,
            "root_session": self.root_session,
            "parent_session_id": self.parent_session_id,
        }
