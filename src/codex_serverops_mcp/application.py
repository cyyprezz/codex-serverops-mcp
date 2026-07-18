from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codex_serverops_mcp.broker.client import BrokerClient
from codex_serverops_mcp.broker.manager import BrokerManager
from codex_serverops_mcp.config import TomlProfileRepository
from codex_serverops_mcp.config.model import validate_profile_name
from codex_serverops_mcp.config.presentation import profile_details, profile_summary
from codex_serverops_mcp.errors import ConfigurationError
from codex_serverops_mcp.identifiers import validate_session_id
from codex_serverops_mcp.security import ApplicationAudit, AuditLogger
from codex_serverops_mcp.setup.service import SetupCoordinator


class BrokerProvider(Protocol):
    def connect(self) -> BrokerClient: ...


@dataclass(slots=True)
class ApplicationServices:
    profiles: TomlProfileRepository
    broker: BrokerProvider
    setup: SetupCoordinator | None = None
    audit: AuditLogger | None = None

    @classmethod
    def create(cls) -> ApplicationServices:
        return cls(
            TomlProfileRepository(),
            BrokerManager(),
            SetupCoordinator.create(),
            AuditLogger(),
        )

    def server_profile_setup(
        self,
        action: str,
        *,
        profile_name: str | None = None,
        suggested_host: str | None = None,
        suggested_user: str | None = None,
        request_id: str | None = None,
        wait_timeout: float | None = None,
    ) -> dict[str, object]:
        setup = self.setup
        if setup is None:
            raise RuntimeError("setup coordinator is unavailable")
        if action in {"add", "edit", "remove", "test"}:
            self._forbid(request_id, "request_id", action)
            self._forbid(wait_timeout, "wait_timeout", action)
            return setup.start(
                action,
                profile_name=profile_name,
                suggested_host=suggested_host,
                suggested_user=suggested_user,
            )
        if action in {"status", "wait"}:
            self._forbid(profile_name, "profile_name", action)
            self._forbid(suggested_host, "suggested_host", action)
            self._forbid(suggested_user, "suggested_user", action)
            if request_id is None:
                raise ValueError("request_id is required")
            if action == "status":
                self._forbid(wait_timeout, "wait_timeout", action)
                return setup.status(request_id)
            return setup.wait(request_id, 5 if wait_timeout is None else wait_timeout)
        raise ValueError(f"unsupported server_profile_setup action: {action}")

    def server_profiles(self, action: str, profile_name: str | None = None) -> dict[str, object]:
        snapshot = self.profiles.load()
        if action == "list":
            if profile_name is not None:
                raise ValueError("profile_name is not valid for list")
            return {
                "profiles": [
                    profile_summary(name, profile)
                    for name, profile in sorted(snapshot.config.profiles.items())
                ]
            }
        if action == "inspect":
            name = self._profile_name(profile_name)
            try:
                profile = snapshot.config.profiles[name]
            except KeyError as error:
                raise ConfigurationError(f"profile does not exist: {name}") from error
            return {"profile": profile_details(name, profile)}
        raise ValueError(f"unsupported server_profiles action: {action}")

    def server_connection(
        self,
        action: str,
        *,
        profile_name: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        if action == "open":
            self._forbid(session_id, "session_id", action)
            return self._broker_request(
                "session.open",
                {"profile_name": self._profile_name(profile_name)},
            )
        if action == "list":
            self._forbid(profile_name, "profile_name", action)
            self._forbid(session_id, "session_id", action)
            return self._broker_request("session.list")
        if action in {"status", "rediscover", "close"}:
            self._forbid(profile_name, "profile_name", action)
            session = self._session_id(session_id)
            return self._broker_request(f"session.{action}", {"session_id": session})
        raise ValueError(f"unsupported server_connection action: {action}")

    def server_exec(
        self,
        session_id: str,
        command: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, object]:
        if not isinstance(command, str) or not command or "\0" in command:
            raise ValueError("command must be non-empty text without NUL")
        payload: dict[str, object] = {
            "session_id": self._session_id(session_id),
            "command": command,
        }
        if timeout is not None:
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, int | float)
                or not 0.1 <= timeout <= 3_600
            ):
                raise ValueError("timeout must be from 0.1 through 3600 seconds")
            payload["timeout"] = float(timeout)
        return self._broker_request("session.exec", payload)

    def server_terminal(
        self,
        action: str,
        session_id: str,
        **parameters: object,
    ) -> dict[str, object]:
        payload = {
            "session_id": self._session_id(session_id),
            "action": action,
            **{name: value for name, value in parameters.items() if value is not None},
        }
        return self._broker_request("session.terminal", payload)

    def server_files(
        self,
        action: str,
        session_id: str,
        **parameters: object,
    ) -> dict[str, object]:
        payload = {
            "session_id": self._session_id(session_id),
            "action": action,
            **{name: value for name, value in parameters.items() if value is not None},
        }
        return self._broker_request("session.files", payload)

    def server_file_edit(
        self,
        action: str,
        session_id: str,
        **parameters: object,
    ) -> dict[str, object]:
        payload = {
            "session_id": self._session_id(session_id),
            "action": action,
            **{name: value for name, value in parameters.items() if value is not None},
        }
        return self._broker_request("session.file_edit", payload)

    def server_elevation(
        self,
        action: str,
        session_id: str,
        *,
        command: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "session_id": self._session_id(session_id),
            "action": action,
        }
        if action == "exec":
            if not isinstance(command, str) or not command or "\0" in command:
                raise ValueError("command is required for elevation exec")
            payload["command"] = command
            if timeout is not None:
                if (
                    isinstance(timeout, bool)
                    or not isinstance(timeout, int | float)
                    or not 0.1 <= timeout <= 3_600
                ):
                    raise ValueError("timeout must be from 0.1 through 3600 seconds")
                payload["timeout"] = float(timeout)
        else:
            self._forbid(command, "command", action)
            self._forbid(timeout, "timeout", action)
        return self._broker_request("session.elevation", payload)

    def _broker_request(
        self,
        message_type: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        request_payload = payload or {}
        tool, action = self._audit_operation(message_type, request_payload)

        def operation() -> dict[str, object]:
            with self.broker.connect() as client:
                return client.request(message_type, payload)

        return ApplicationAudit(self.audit).call(
            tool,
            action,
            operation,
            profile=self._optional_text(request_payload.get("profile_name")),
            session_id=self._optional_text(request_payload.get("session_id")),
            command=(
                self._optional_text(request_payload.get("command"))
                if tool in {"server_exec", "server_elevation"}
                or (tool == "server_terminal" and action == "start")
                else None
            ),
        )

    @staticmethod
    def _audit_operation(
        message_type: str,
        payload: dict[str, object],
    ) -> tuple[str, str]:
        mapping = {
            "session.open": "server_connection",
            "session.list": "server_connection",
            "session.status": "server_connection",
            "session.rediscover": "server_connection",
            "session.close": "server_connection",
            "session.exec": "server_exec",
            "session.terminal": "server_terminal",
            "session.files": "server_files",
            "session.file_edit": "server_file_edit",
            "session.elevation": "server_elevation",
        }
        try:
            tool = mapping[message_type]
        except KeyError as error:
            raise ValueError(f"broker operation has no audit mapping: {message_type}") from error
        explicit_action = payload.get("action")
        action = (
            explicit_action
            if isinstance(explicit_action, str)
            else "exec" if message_type == "session.exec" else message_type.rsplit(".", 1)[-1]
        )
        return tool, action

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _profile_name(value: str | None) -> str:
        if value is None:
            raise ValueError("profile_name is required")
        validate_profile_name(value)
        return value

    @staticmethod
    def _session_id(value: str | None) -> str:
        if value is None:
            raise ValueError("session_id is required")
        validate_session_id(value)
        return value

    @staticmethod
    def _forbid(value: object | None, field_name: str, action: str) -> None:
        if value is not None:
            raise ValueError(f"{field_name} is not valid for {action}")
