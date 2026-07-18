from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .service import WorkerSessionService


@dataclass(frozen=True, slots=True)
class WorkerReply:
    payload: dict[str, object]
    stop: bool = False


class SessionService(Protocol):
    def open(self) -> dict[str, object]: ...

    def execute(self, command: str, timeout: float | None = None) -> dict[str, object]: ...

    def terminal(self, action: str, payload: Mapping[str, object]) -> dict[str, object]: ...

    def files(
        self,
        action: str,
        payload: Mapping[str, object],
        *,
        write: bool,
    ) -> dict[str, object]: ...

    def elevation(
        self,
        action: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]: ...

    def status(self) -> dict[str, object]: ...

    def close(self) -> None: ...


class WorkerProtocolHandler:
    def __init__(
        self,
        session_id: str,
        profile_name: str,
        *,
        service: SessionService | None = None,
        root_session: bool = False,
    ) -> None:
        self.session_id = session_id
        self.profile_name = profile_name
        self.service = service or WorkerSessionService(
            profile_name,
            root_session=root_session,
        )

    def handle(self, message_type: str, raw_payload: Mapping[str, object]) -> WorkerReply:
        payload = dict(raw_payload)
        if message_type == "worker.ping":
            self._fields(payload, set())
            return WorkerReply(self._status_payload())
        if message_type == "worker.status":
            self._fields(payload, set())
            return WorkerReply(self._status_payload())
        if message_type == "worker.open":
            self._fields(payload, set())
            return WorkerReply(self._identity(self.service.open()))
        if message_type == "worker.exec":
            self._fields(payload, {"command"}, optional={"timeout"})
            command = payload["command"]
            timeout = payload.get("timeout")
            if not isinstance(command, str):
                raise ValueError("command must be a string")
            if timeout is not None and (
                isinstance(timeout, bool) or not isinstance(timeout, int | float)
            ):
                raise ValueError("timeout must be a number")
            if timeout is not None and not 0.1 <= float(timeout) <= 3_600:
                raise ValueError("timeout is outside the supported range")
            return WorkerReply(
                self.service.execute(command, None if timeout is None else float(timeout))
            )
        if message_type == "worker.terminal":
            action = payload.get("action")
            if not isinstance(action, str):
                raise ValueError("terminal action must be a string")
            expected, optional = self._terminal_fields(action)
            self._fields(payload, expected | {"action"}, optional=optional)
            operation_payload = dict(payload)
            del operation_payload["action"]
            return WorkerReply(self.service.terminal(action, operation_payload))
        if message_type in {"worker.files", "worker.file_edit"}:
            action = payload.get("action")
            if not isinstance(action, str):
                raise ValueError("file action must be a string")
            expected, optional = self._file_fields(
                action,
                write=message_type == "worker.file_edit",
            )
            self._fields(payload, expected | {"action"}, optional=optional)
            operation_payload = dict(payload)
            del operation_payload["action"]
            return WorkerReply(
                self.service.files(
                    action,
                    operation_payload,
                    write=message_type == "worker.file_edit",
                )
            )
        if message_type == "worker.elevation":
            action = payload.get("action")
            if not isinstance(action, str):
                raise ValueError("elevation action must be a string")
            expected, optional = self._elevation_fields(action)
            self._fields(payload, expected | {"action"}, optional=optional)
            operation_payload = dict(payload)
            del operation_payload["action"]
            return WorkerReply(self.service.elevation(action, operation_payload))
        if message_type == "worker.shutdown":
            self._fields(payload, set())
            self.service.close()
            return WorkerReply({"status": "closing"}, stop=True)
        raise ValueError(f"unknown worker message type: {message_type}")

    def error_payload(self, error: BaseException) -> dict[str, object]:
        return {
            "code": getattr(error, "code", "invalid_request"),
            "message": str(error),
            "state": self.service.status()["state"],
        }

    def _status_payload(self) -> dict[str, object]:
        return self._identity(self.service.status())

    def _identity(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "profile_name": self.profile_name,
            "pid": os.getpid(),
            **payload,
        }

    @staticmethod
    def _fields(
        payload: Mapping[str, object],
        required: set[str],
        *,
        optional: set[str] = frozenset(),
    ) -> None:
        fields = set(payload)
        if not required.issubset(fields) or not fields.issubset(required | set(optional)):
            raise ValueError("worker request fields do not match the operation")

    @staticmethod
    def _terminal_fields(action: str) -> tuple[set[str], set[str]]:
        operations = {
            "start": ({"command"}, set()),
            "read": ({"cursor"}, {"timeout"}),
            "write": ({"text"}, set()),
            "interrupt": (set(), set()),
            "resize": ({"columns", "rows"}, set()),
            "status": (set(), set()),
            "close": (set(), {"timeout"}),
        }
        try:
            return operations[action]
        except KeyError as error:
            raise ValueError(f"unsupported terminal action: {action}") from error

    @staticmethod
    def _file_fields(action: str, *, write: bool) -> tuple[set[str], set[str]]:
        operations = (
            {
                "write_text": ({"path", "content"}, {"expected_sha256"}),
                "apply_patch": ({"path", "patch"}, {"expected_sha256"}),
                "mkdir": ({"path"}, set()),
                "rename": ({"path", "destination_path"}, set()),
                "remove": ({"path"}, {"recursive", "expected_sha256"}),
            }
            if write
            else {
                "list": ({"path"}, {"max_results"}),
                "stat": ({"path"}, set()),
                "read_text": ({"path"}, {"byte_limit", "start_line", "end_line"}),
                "search_text": ({"path", "query"}, {"max_results"}),
                "hash": ({"path"}, set()),
            }
        )
        try:
            return operations[action]
        except KeyError as error:
            kind = "edit" if write else "read"
            raise ValueError(f"unsupported file {kind} action: {action}") from error

    @staticmethod
    def _elevation_fields(action: str) -> tuple[set[str], set[str]]:
        operations = {
            "acquire": (set(), set()),
            "status": (set(), set()),
            "release": (set(), set()),
            "exec": ({"command"}, {"timeout"}),
        }
        try:
            return operations[action]
        except KeyError as error:
            raise ValueError(f"unsupported worker elevation action: {action}") from error
