from __future__ import annotations

import queue
import secrets
import threading
import time
from contextlib import suppress
from dataclasses import dataclass

from codex_serverops_mcp.ipc.connection import PipeConnection
from codex_serverops_mcp.ipc.constants import MAX_AUTH_MESSAGE_BYTES
from codex_serverops_mcp.ipc.errors import (
    IpcClosed,
    IpcError,
    IpcTimeout,
)
from codex_serverops_mcp.ipc.handshake import server_handshake
from codex_serverops_mcp.ipc.messages import Envelope
from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener, connect_named_pipe
from codex_serverops_mcp.ipc.security import pipe_name_for_current_user
from codex_serverops_mcp.ssh.prompts import PromptEvent

from .errors import (
    AuthenticationProtocolError,
    AuthenticationReplayError,
    AuthenticationTimedOut,
)
from .model import AuthPrompt, AuthTargetContext
from .wire import AuthResponse, decode_auth_response


@dataclass(frozen=True, slots=True)
class AuthLaunchDescriptor:
    request_id: str
    pipe: str
    token: str
    expires_at: float


class AuthChallengeServer:
    def __init__(
        self,
        target: AuthTargetContext,
        event: PromptEvent,
        *,
        timeout: float = 120,
    ) -> None:
        if not 0.1 <= timeout <= 300:
            raise ValueError("authentication timeout must be from 0.1 through 300 seconds")
        request_hex = secrets.token_hex(16)
        self.request_id = f"auth_{request_hex}"
        self.pipe = pipe_name_for_current_user(f"auth-{request_hex[:16]}")
        self.token = secrets.token_urlsafe(32)
        self.expires_at = time.time() + timeout
        self._deadline = time.monotonic() + timeout
        self.prompt = AuthPrompt.from_event(
            self.request_id,
            target,
            event,
            expires_at=self.expires_at,
        )
        self.listener = NamedPipeListener(self.pipe)
        self._lock = threading.Lock()
        self._collect_started = False
        self._authenticated = False

    @property
    def descriptor(self) -> AuthLaunchDescriptor:
        return AuthLaunchDescriptor(
            self.request_id,
            self.pipe,
            self.token,
            self.expires_at,
        )

    def collect(self) -> AuthResponse:
        with self._lock:
            if self._collect_started:
                raise AuthenticationReplayError("authentication request was already consumed")
            self._collect_started = True
        try:
            while time.monotonic() < self._deadline:
                connection = self._accept_before_deadline()
                with connection:
                    try:
                        server_handshake(
                            connection,
                            self.token,
                            expected_role="auth",
                            timeout=max(0, self._deadline - time.monotonic()),
                        )
                    except IpcTimeout as error:
                        raise AuthenticationTimedOut("authentication window timed out") from error
                    except IpcError:
                        continue
                    with self._lock:
                        if self._authenticated:
                            raise AuthenticationReplayError(
                                "authentication request was already authenticated"
                            )
                        self._authenticated = True
                    return self._receive_response(connection)
            raise AuthenticationTimedOut("authentication window timed out")
        finally:
            self.listener.close()

    def close(self) -> None:
        self.listener.close()

    def _receive_response(self, connection: PipeConnection) -> AuthResponse:
        connection.send(
            Envelope.create("auth.challenge", self.prompt.to_payload()),
            max_bytes=MAX_AUTH_MESSAGE_BYTES,
        )
        try:
            frame = connection.receive_bytes(
                max_bytes=MAX_AUTH_MESSAGE_BYTES,
                timeout=max(0, self._deadline - time.monotonic()),
            )
        except IpcTimeout as error:
            raise AuthenticationTimedOut("authentication window timed out") from error
        except (IpcClosed, IpcError) as error:
            raise AuthenticationProtocolError(
                "authentication window disconnected without a response"
            ) from error
        try:
            response = decode_auth_response(frame)
        finally:
            del frame
        connection.send(
            Envelope.create(
                "auth.response.ack",
                {"status": response.status},
            ),
            max_bytes=MAX_AUTH_MESSAGE_BYTES,
        )
        return response

    def _accept_before_deadline(self) -> PipeConnection:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise AuthenticationTimedOut("authentication window timed out")
        results: queue.Queue[PipeConnection | BaseException] = queue.Queue(maxsize=1)

        def accept() -> None:
            try:
                results.put(self.listener.accept())
            except BaseException as error:
                results.put(error)

        thread = threading.Thread(target=accept, name="serverops-auth-accept", daemon=True)
        thread.start()
        thread.join(timeout=remaining)
        if thread.is_alive():
            self._wake_accept()
            thread.join(timeout=2)
            if not thread.is_alive():
                item = results.get_nowait()
                if isinstance(item, PipeConnection):
                    item.close()
            raise AuthenticationTimedOut("authentication window timed out")
        item = results.get_nowait()
        if isinstance(item, BaseException):
            raise AuthenticationProtocolError("authentication pipe accept failed") from item
        return item

    def _wake_accept(self) -> None:
        with suppress(IpcError):
            connect_named_pipe(self.pipe, timeout=0.5).close()
