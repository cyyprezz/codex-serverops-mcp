from __future__ import annotations

import threading
from pathlib import Path

from codex_serverops_mcp import BROKER_PROTOCOL_VERSION
from codex_serverops_mcp.ipc.connection import PipeConnection
from codex_serverops_mcp.ipc.errors import IpcError
from codex_serverops_mcp.ipc.handshake import client_handshake
from codex_serverops_mcp.ipc.messages import Envelope
from codex_serverops_mcp.ipc.named_pipe import connect_named_pipe
from codex_serverops_mcp.runtime import RuntimeDirectory

from .errors import (
    BrokerOutcomeUnknown,
    BrokerRemoteError,
    BrokerRequestError,
    BrokerUnavailable,
)
from .outcomes import uncertain_outcome_code
from .timeouts import broker_response_timeout


class BrokerClient:
    def __init__(self, runtime_path: Path | None = None, *, timeout: float = 5) -> None:
        self.runtime = RuntimeDirectory(runtime_path)
        try:
            status = self.runtime.read_json(self.runtime.broker_status_path)
        except (OSError, ValueError) as error:
            raise BrokerUnavailable("broker status is unavailable") from error
        self._validate_status(status)
        connection: PipeConnection | None = None
        try:
            connection = connect_named_pipe(str(status["pipe"]), timeout=timeout)
            client_handshake(
                connection,
                str(status["instance_token"]),
                timeout=timeout,
            )
        except IpcError as error:
            if connection is not None:
                connection.close()
            raise BrokerUnavailable("broker connection failed") from error
        self.connection = connection
        self._lock = threading.Lock()

    def request(
        self,
        message_type: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        request = Envelope.create(message_type, payload)
        try:
            with self._lock:
                connection = self.connection
                if connection is None:
                    raise BrokerUnavailable("broker client is closed")
                connection.send(request)
                response = connection.receive(
                    timeout=broker_response_timeout(message_type, payload)
                )
        except IpcError as error:
            self.close()
            self._raise_transport_failure(message_type, payload, error)
        if response.message_id != request.message_id:
            self.close()
            self._raise_transport_failure(
                message_type,
                payload,
                BrokerRequestError("broker response correlation ID does not match"),
            )
        if response.message_type == "error":
            code = response.payload.get("code", "broker_request_failed")
            message = response.payload.get("message", "broker request failed")
            if not isinstance(code, str) or not isinstance(message, str):
                self.close()
                self._raise_transport_failure(
                    message_type,
                    payload,
                    BrokerRequestError("broker error response is invalid"),
                )
            raise BrokerRemoteError(code, message)
        if response.message_type != f"{message_type}.result":
            self.close()
            self._raise_transport_failure(
                message_type,
                payload,
                BrokerRequestError("broker response type does not match the request"),
            )
        return dict(response.payload)

    @staticmethod
    def _raise_transport_failure(
        message_type: str,
        payload: dict[str, object] | None,
        error: BaseException,
    ) -> None:
        code = uncertain_outcome_code(message_type, payload)
        if code is not None:
            raise BrokerOutcomeUnknown(
                code,
                "The broker connection failed after request delivery; the operation "
                "must not be retried automatically.",
            ) from error
        raise BrokerUnavailable("broker connection failed during request") from error

    def close(self) -> None:
        connection = self.connection
        self.connection = None
        if connection is not None:
            connection.close()

    @staticmethod
    def _validate_status(status: dict[str, object]) -> None:
        expected = {"pid", "pipe", "protocol_version", "instance_token", "started_at"}
        if set(status) != expected:
            raise BrokerUnavailable("broker status fields are invalid")
        if status["protocol_version"] != BROKER_PROTOCOL_VERSION:
            raise BrokerUnavailable("broker protocol version is incompatible")
        if (
            isinstance(status["pid"], bool)
            or not isinstance(status["pid"], int)
            or status["pid"] < 1
            or not isinstance(status["pipe"], str)
            or not isinstance(status["instance_token"], str)
            or len(status["instance_token"]) < 32
        ):
            raise BrokerUnavailable("broker connection details are invalid")

    def __enter__(self) -> BrokerClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
