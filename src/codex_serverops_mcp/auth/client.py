from __future__ import annotations

import time

from codex_serverops_mcp.ipc.connection import PipeConnection
from codex_serverops_mcp.ipc.constants import MAX_AUTH_MESSAGE_BYTES
from codex_serverops_mcp.ipc.errors import IpcError
from codex_serverops_mcp.ipc.handshake import client_handshake
from codex_serverops_mcp.ipc.named_pipe import connect_named_pipe

from .errors import AuthenticationProtocolError, AuthenticationTimedOut
from .model import AuthPrompt
from .wire import (
    AuthResponseKind,
    decision_response_frame,
    secret_response_frame,
)


class DirectAuthClient:
    def __init__(
        self,
        pipe: str,
        request_id: str,
        token: str,
        *,
        timeout: float = 5,
    ) -> None:
        self.pipe = pipe
        self.request_id = request_id
        self.token = token
        self.timeout = timeout
        self.connection: PipeConnection | None = None
        self.prompt: AuthPrompt | None = None
        self._finished = False

    def open(self) -> AuthPrompt:
        if self.connection is not None or self._finished:
            raise AuthenticationProtocolError("authentication client is already used")
        connection: PipeConnection | None = None
        try:
            connection = connect_named_pipe(self.pipe, timeout=self.timeout)
            client_handshake(connection, self.token, role="auth", timeout=self.timeout)
            challenge = connection.receive(
                max_bytes=MAX_AUTH_MESSAGE_BYTES,
                timeout=self.timeout,
            )
        except IpcError as error:
            if connection is not None:
                connection.close()
            raise AuthenticationProtocolError("authentication connection failed") from error
        if challenge.message_type != "auth.challenge":
            connection.close()
            raise AuthenticationProtocolError("authentication challenge type is invalid")
        try:
            prompt = AuthPrompt.from_payload(challenge.payload)
        except (TypeError, ValueError) as error:
            connection.close()
            raise AuthenticationProtocolError("authentication challenge is invalid") from error
        if prompt.request_id != self.request_id:
            connection.close()
            raise AuthenticationProtocolError("authentication request ID does not match")
        if prompt.expires_at <= time.time():
            connection.close()
            raise AuthenticationTimedOut("authentication request already expired")
        self.connection = connection
        self.prompt = prompt
        return prompt

    def submit_secret(self, secret: bytearray) -> str:
        frame: bytearray | None = None
        try:
            frame = secret_response_frame(secret)
        finally:
            secret[:] = b"\0" * len(secret)
        try:
            return self._finish(frame, "submitted")
        finally:
            frame[:] = b"\0" * len(frame)

    def confirm(self) -> str:
        return self._finish(decision_response_frame(AuthResponseKind.CONFIRM), "confirmed")

    def reject(self) -> str:
        return self._finish(decision_response_frame(AuthResponseKind.REJECT), "rejected")

    def cancel(self) -> str:
        return self._finish(decision_response_frame(AuthResponseKind.CANCEL), "cancelled")

    def report_timeout(self) -> str:
        return self._finish(decision_response_frame(AuthResponseKind.TIMEOUT), "timed_out")

    def close(self) -> None:
        connection = self.connection
        self.connection = None
        if connection is not None:
            connection.close()

    def _finish(self, frame: bytes | bytearray, expected_status: str) -> str:
        if self._finished:
            raise AuthenticationProtocolError("authentication response was already sent")
        connection = self.connection
        if connection is None:
            raise AuthenticationProtocolError("authentication client is not connected")
        self._finished = True
        try:
            connection.send_bytes(frame, max_bytes=MAX_AUTH_MESSAGE_BYTES)
            acknowledgement = connection.receive(
                max_bytes=MAX_AUTH_MESSAGE_BYTES,
                timeout=self.timeout,
            )
        except IpcError as error:
            raise AuthenticationProtocolError(
                "authentication response was not acknowledged"
            ) from error
        finally:
            self.close()
        if acknowledgement.message_type != "auth.response.ack":
            raise AuthenticationProtocolError("authentication acknowledgement type is invalid")
        if dict(acknowledgement.payload) != {"status": expected_status}:
            raise AuthenticationProtocolError("authentication acknowledgement is invalid")
        return expected_status

    def __enter__(self) -> DirectAuthClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
