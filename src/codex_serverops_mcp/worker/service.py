from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path

from codex_serverops_mcp.auth.model import AuthTargetContext
from codex_serverops_mcp.config import ServerProfile, TomlProfileRepository, default_config_path
from codex_serverops_mcp.elevation import ElevationService
from codex_serverops_mcp.elevation.errors import ElevationError
from codex_serverops_mcp.errors import ConfigurationError
from codex_serverops_mcp.files import RemoteFileService
from codex_serverops_mcp.files.errors import RemoteFileError
from codex_serverops_mcp.ipc.security import secure_path_for_current_user
from codex_serverops_mcp.ssh.invocation import build_ssh_arguments
from codex_serverops_mcp.ssh.target import ResolvedSshTarget, find_windows_ssh, resolve_ssh_target

from .errors import SessionError
from .result import InteractiveStatus
from .session import StatefulSshSession
from .state import SessionState
from .visible_auth import VisibleAuthenticationCoordinator

SESSION_OPEN_TIMEOUT_SECONDS = 180

SessionFactory = Callable[[ServerProfile, AuthTargetContext], StatefulSshSession]


class WorkerSessionService:
    def __init__(
        self,
        profile_name: str,
        *,
        repository: TomlProfileRepository | None = None,
        ssh_finder: Callable[[], Path] = find_windows_ssh,
        target_resolver: Callable[[ServerProfile, Path], ResolvedSshTarget] = resolve_ssh_target,
        session_factory: SessionFactory | None = None,
        known_hosts_path: Path | None = None,
        root_session: bool = False,
    ) -> None:
        self.profile_name = profile_name
        self.repository = repository or TomlProfileRepository()
        self.ssh_finder = ssh_finder
        self.target_resolver = target_resolver
        self.session_factory = session_factory or self._create_session
        self.known_hosts_path = known_hosts_path or (
            default_config_path().parent / "known_hosts"
        )
        self.root_session = root_session
        self.profile: ServerProfile | None = None
        self.target: ResolvedSshTarget | None = None
        self.session: StatefulSshSession | None = None
        self.cwd: str | None = None

    def open(self) -> dict[str, object]:
        if self.session is not None:
            raise SessionError("worker session is already initialized")
        snapshot = self.repository.load()
        try:
            profile = snapshot.config.profiles[self.profile_name]
        except KeyError as error:
            raise ConfigurationError(f"profile does not exist: {self.profile_name}") from error
        if self.root_session and not profile.allow_root_session:
            raise ElevationError(
                "root_session_disabled",
                "guided root sessions are disabled for this profile",
            )
        ssh_executable = self.ssh_finder()
        target = self.target_resolver(profile, ssh_executable)
        known_hosts = self._prepare_known_hosts()
        auth_target = AuthTargetContext(
            self.profile_name,
            profile.display_name,
            target.host,
            target.port,
            target.user,
        )
        session = self.session_factory(profile, auth_target)
        self.profile = profile
        self.target = target
        self.session = session
        try:
            session.open(
                build_ssh_arguments(
                    profile,
                    ssh_executable=ssh_executable,
                    known_hosts_file=known_hosts,
                    root_session=self.root_session,
                ),
                timeout=SESSION_OPEN_TIMEOUT_SECONDS,
            )
            if self.root_session:
                verification = session.execute(
                    "id -u",
                    timeout=profile.command_timeout_seconds,
                )
                if verification.output.strip() != "0":
                    raise ElevationError(
                        "root_session_verification_failed",
                        "the dedicated session did not reach effective user root",
                    )
                self.cwd = verification.cwd
        except BaseException:
            with suppress(Exception):
                session.close()
            raise
        return self.status()

    def execute(self, command: str, timeout: float | None = None) -> dict[str, object]:
        _session, profile = self._open_session()
        if not profile.allow_terminal:
            raise SessionError("terminal access is disabled for this profile")
        return self._execute_internal(command, timeout)

    def files(
        self,
        action: str,
        payload: Mapping[str, object],
        *,
        write: bool,
    ) -> dict[str, object]:
        if self.root_session:
            raise RemoteFileError(
                "root_session_file_access_disabled",
                "structured file tools are unavailable in root sessions",
            )
        session, profile = self._open_session()
        session.state.require(SessionState.READY)
        service = RemoteFileService(profile, self._execute_internal)
        return service.edit(action, payload) if write else service.read(action, payload)

    def elevation(
        self,
        action: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        session, profile = self._open_session()
        session.state.require(SessionState.READY)
        if self.root_session:
            raise ElevationError(
                "already_elevated",
                "guided sudo actions are unavailable inside a root session",
            )
        assert self.target is not None
        return ElevationService(profile, self.target.user, self._execute_internal).handle(
            action,
            payload,
        )

    def _execute_internal(
        self,
        command: str,
        timeout: float | None = None,
    ) -> dict[str, object]:
        session, profile = self._open_session()
        session.state.require(SessionState.READY)
        result = session.execute(
            command,
            timeout=profile.command_timeout_seconds if timeout is None else timeout,
        )
        self.cwd = result.cwd
        return {
            "status": "completed",
            "exit_code": result.exit_code,
            "cwd": result.cwd,
            "output": result.output,
            "truncated": result.truncated,
            "duration_ms": result.duration_ms,
        }

    def terminal(self, action: str, payload: Mapping[str, object]) -> dict[str, object]:
        session, profile = self._open_session()
        if not profile.allow_terminal:
            raise SessionError("terminal access is disabled for this profile")
        if action == "start":
            command = self._text(payload, "command")
            return self._terminal_status(session.interactive.start(command))
        if action == "read":
            cursor = self._integer(payload, "cursor", minimum=0)
            timeout = self._number(payload, "timeout", default=0, minimum=0, maximum=60)
            result = session.interactive.read(cursor, timeout=timeout)
            return {
                "status": "running",
                "state": result.state.value,
                "output": result.output,
                "next_cursor": result.next_cursor,
                "dropped_before_cursor": result.dropped_before_cursor,
            }
        if action == "write":
            return self._terminal_status(session.interactive.write(self._text(payload, "text")))
        if action == "interrupt":
            return self._terminal_status(session.interactive.interrupt())
        if action == "resize":
            columns = self._integer(payload, "columns", minimum=1, maximum=32_767)
            rows = self._integer(payload, "rows", minimum=1, maximum=32_767)
            return self._terminal_status(session.interactive.resize(columns, rows))
        if action == "status":
            return self._terminal_status(session.interactive.status())
        if action == "close":
            timeout = self._number(payload, "timeout", default=5, minimum=0.1, maximum=60)
            return self._terminal_status(session.interactive.close(timeout=timeout))
        raise ValueError(f"unsupported terminal action: {action}")

    def status(self) -> dict[str, object]:
        state = self.session.state.state if self.session is not None else SessionState.CREATED
        target = self.target
        profile = self.profile
        return {
            "profile_name": self.profile_name,
            "state": state.value,
            "cwd": self.cwd,
            "ssh_user": None if target is None else target.user,
            "effective_user": (
                None if target is None else "root" if self.root_session else target.user
            ),
            "elevated": self.root_session,
            "root_session": self.root_session,
            "environment": None if profile is None else profile.environment,
        }

    def close(self) -> None:
        if self.session is not None:
            self.session.close()

    def _open_session(self) -> tuple[StatefulSshSession, ServerProfile]:
        if self.session is None or self.profile is None:
            raise SessionError("worker session has not been opened")
        return self.session, self.profile

    def _prepare_known_hosts(self) -> Path:
        path = self.known_hosts_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        secure_path_for_current_user(str(path.parent), directory=True)
        path.touch(exist_ok=True)
        secure_path_for_current_user(str(path))
        return path

    @staticmethod
    def _create_session(
        profile: ServerProfile,
        target: AuthTargetContext,
    ) -> StatefulSshSession:
        return StatefulSshSession(
            authenticator=VisibleAuthenticationCoordinator(target),
            max_output_bytes=profile.max_output_bytes,
        )

    @staticmethod
    def _terminal_status(status: InteractiveStatus) -> dict[str, object]:
        return {
            "status": "running" if status.running else "stopped",
            "state": status.state.value,
            "running": status.running,
            "output_cursor": status.output_cursor,
        }

    @staticmethod
    def _text(payload: Mapping[str, object], name: str) -> str:
        value = payload[name]
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        return value

    @staticmethod
    def _integer(
        payload: Mapping[str, object],
        name: str,
        *,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        value = payload[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if value < minimum or (maximum is not None and value > maximum):
            raise ValueError(f"{name} is outside the supported range")
        return value

    @staticmethod
    def _number(
        payload: Mapping[str, object],
        name: str,
        *,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        value = payload.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{name} must be a number")
        result = float(value)
        if not minimum <= result <= maximum:
            raise ValueError(f"{name} is outside the supported range")
        return result
