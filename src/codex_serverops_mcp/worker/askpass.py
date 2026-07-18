from __future__ import annotations

import secrets
import shutil
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

from codex_serverops_mcp.auth.askpass import (
    ASKPASS_CANCELLED,
    ASKPASS_FAILED,
    ASKPASS_MODE_ENVIRONMENT,
    ASKPASS_PIPE_ENVIRONMENT,
    ASKPASS_REJECTED,
    ASKPASS_RESPONSE,
    ASKPASS_TIMED_OUT,
    ASKPASS_TOKEN_ENVIRONMENT,
)
from codex_serverops_mcp.auth.errors import (
    AuthenticationCancelled,
    AuthenticationProtocolError,
    AuthenticationRejected,
    AuthenticationTimedOut,
)
from codex_serverops_mcp.auth.model import AuthTargetContext
from codex_serverops_mcp.ipc.connection import PipeConnection
from codex_serverops_mcp.ipc.constants import MAX_AUTH_MESSAGE_BYTES
from codex_serverops_mcp.ipc.errors import IpcError
from codex_serverops_mcp.ipc.handshake import server_handshake
from codex_serverops_mcp.ipc.named_pipe import (
    NamedPipeListener,
    connect_named_pipe,
)
from codex_serverops_mcp.ipc.security import pipe_name_for_current_user
from codex_serverops_mcp.ssh.auth_policy import (
    ConnectionPromptPolicy,
    PromptPolicyError,
    classify_askpass_prompt,
)

from .authentication import AuthenticationCoordinator


class _RelaySecretSink:
    def __init__(self) -> None:
        self.secret: bytearray | None = None

    @property
    def used(self) -> bool:
        return self.secret is not None

    def submit(self, response: bytearray) -> None:
        if self.secret is not None:
            raise AuthenticationProtocolError("Askpass response was already supplied")
        try:
            self.secret = bytearray(response)
        finally:
            response[:] = b"\0" * len(response)


class OpenSshAskpassRelay:
    def __init__(
        self,
        target: AuthTargetContext,
        policy: ConnectionPromptPolicy,
        authenticator: AuthenticationCoordinator,
        *,
        executable: Path | None = None,
        timeout: float = 180,
    ) -> None:
        request_hex = secrets.token_hex(16)
        self.target = target
        self.policy = policy
        self.authenticator = authenticator
        self.timeout = timeout
        self.pipe = pipe_name_for_current_user(f"askpass-{request_hex[:16]}")
        self.token = secrets.token_urlsafe(32)
        self.executable = executable or find_serverops_auth()
        self.listener = NamedPipeListener(self.pipe)
        self.security_report = self.listener.security_report
        self._deadline = time.monotonic() + timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failure: BaseException | None = None
        self._failure_lock = threading.Lock()

    @property
    def environment(self) -> dict[str, str]:
        return {
            "DISPLAY": "serverops-askpass",
            "SSH_ASKPASS": str(self.executable),
            "SSH_ASKPASS_REQUIRE": "force",
            ASKPASS_MODE_ENVIRONMENT: "1",
            ASKPASS_PIPE_ENVIRONMENT: self.pipe,
            ASKPASS_TOKEN_ENVIRONMENT: self.token,
        }

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Askpass relay is already started")
        self._thread = threading.Thread(
            target=self._serve,
            name="serverops-askpass-relay",
            daemon=True,
        )
        self._thread.start()

    def check(self) -> None:
        with self._failure_lock:
            failure = self._failure
        if failure is not None:
            raise failure

    def close(self) -> None:
        self._stop.set()
        self.authenticator.cancel_active()
        with suppress(IpcError):
            connect_named_pipe(self.pipe, timeout=0.5).close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        try:
            self.listener.close()
        finally:
            self.token = ""
        if thread is not None and thread.is_alive():
            error = AuthenticationProtocolError(
                "Askpass relay did not stop after authentication cancellation"
            )
            self._set_failure(error)
            raise error

    def _serve(self) -> None:
        while not self._stop.is_set() and time.monotonic() < self._deadline:
            try:
                connection = self.listener.accept()
            except BaseException:
                if not self._stop.is_set():
                    self._set_failure(AuthenticationProtocolError("Askpass relay accept failed"))
                return
            with connection:
                if self._stop.is_set():
                    return
                try:
                    server_handshake(
                        connection,
                        self.token,
                        expected_role="askpass",
                        timeout=min(5, max(0, self._deadline - time.monotonic())),
                    )
                except IpcError:
                    continue
                try:
                    self._handle_request(connection)
                except BaseException as error:
                    self._set_failure(error)
                    return

    def _handle_request(self, connection: PipeConnection) -> None:
        request = connection.receive(
            max_bytes=MAX_AUTH_MESSAGE_BYTES,
            timeout=min(5, max(0, self._deadline - time.monotonic())),
        )
        if request.message_type != "askpass.prompt" or set(request.payload) != {"prompt"}:
            raise AuthenticationProtocolError("Askpass request fields are invalid")
        prompt = request.payload["prompt"]
        if not isinstance(prompt, str):
            raise AuthenticationProtocolError("Askpass prompt is not text")
        try:
            event = classify_askpass_prompt(prompt)
            self.policy.authorize(event)
        except PromptPolicyError as error:
            connection.send_bytes(bytes((ASKPASS_FAILED,)))
            raise AuthenticationProtocolError(str(error)) from error
        sink = _RelaySecretSink()
        try:
            self.authenticator.respond(event, sink)  # type: ignore[arg-type]
        except AuthenticationRejected:
            connection.send_bytes(bytes((ASKPASS_REJECTED,)))
            raise
        except AuthenticationCancelled:
            connection.send_bytes(bytes((ASKPASS_CANCELLED,)))
            raise
        except AuthenticationTimedOut:
            connection.send_bytes(bytes((ASKPASS_TIMED_OUT,)))
            raise
        if not sink.used or sink.secret is None:
            raise AuthenticationProtocolError("authentication window returned no Askpass response")
        response = bytearray((ASKPASS_RESPONSE,))
        response.extend(sink.secret)
        try:
            self.policy.record_answer(event.kind)
            connection.send_bytes(response)
        finally:
            response[:] = b"\0" * len(response)
            sink.secret[:] = b"\0" * len(sink.secret)
            sink.secret.clear()

    def _set_failure(self, error: BaseException) -> None:
        with self._failure_lock:
            if self._failure is None:
                self._failure = error
        self._stop.set()


def find_serverops_auth() -> Path:
    adjacent = Path(sys.executable).with_name("serverops-auth.exe")
    if adjacent.is_file():
        return adjacent.resolve()
    found = shutil.which("serverops-auth.exe") or shutil.which("serverops-auth")
    if found:
        return Path(found).resolve()
    raise FileNotFoundError("serverops-auth executable was not found beside the worker runtime")
