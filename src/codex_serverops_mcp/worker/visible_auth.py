from __future__ import annotations

import subprocess
import threading

from codex_serverops_mcp.auth.errors import (
    AuthenticationCancelled,
    AuthenticationProtocolError,
    AuthenticationRejected,
    AuthenticationTimedOut,
)
from codex_serverops_mcp.auth.launcher import (
    AuthLauncher,
    AuthProcess,
    VisibleAuthProcessLauncher,
)
from codex_serverops_mcp.auth.model import AuthTargetContext
from codex_serverops_mcp.auth.server import AuthChallengeServer
from codex_serverops_mcp.auth.wire import AuthResponse, AuthResponseKind
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind

from .authentication import SecretInputSink


class VisibleAuthenticationCoordinator:
    """Worker-local authentication coordinator; no broker message carries the response."""

    def __init__(
        self,
        target: AuthTargetContext,
        *,
        launcher: AuthLauncher | None = None,
        timeout: float = 120,
    ) -> None:
        self.target = target
        self.launcher = launcher or VisibleAuthProcessLauncher()
        self.timeout = timeout
        self._active_lock = threading.Lock()
        self._active_challenge: AuthChallengeServer | None = None
        self._active_process: AuthProcess | None = None
        self._cancel_requested = False

    def respond(self, event: PromptEvent, sink: SecretInputSink) -> None:
        challenge = AuthChallengeServer(self.target, event, timeout=self.timeout)
        process: AuthProcess | None = None
        response: AuthResponse | None = None
        with self._active_lock:
            if self._active_challenge is not None:
                raise AuthenticationProtocolError(
                    "another authentication window is already active"
                )
            self._active_challenge = challenge
            self._active_process = None
            self._cancel_requested = False
        try:
            process = self.launcher.launch(challenge.descriptor)
            with self._active_lock:
                self._active_process = process
                cancel_requested = self._cancel_requested
            if cancel_requested:
                challenge.cancel()
                self._cancel_process(process)
            response = challenge.collect()
            self._apply_response(event.kind, response, sink)
        finally:
            with self._active_lock:
                if self._active_challenge is challenge:
                    self._active_challenge = None
                    self._active_process = None
                    self._cancel_requested = False
            challenge.close()
            if response is not None:
                response.clear()
            if process is not None:
                self._finish_process(process)

    def cancel_active(self) -> None:
        with self._active_lock:
            challenge = self._active_challenge
            process = self._active_process
            if challenge is None:
                return
            self._cancel_requested = True
        challenge.cancel()
        if process is not None:
            self._cancel_process(process)

    @staticmethod
    def _apply_response(
        prompt_kind: PromptKind,
        response: AuthResponse,
        sink: SecretInputSink,
    ) -> None:
        if response.kind is AuthResponseKind.CANCEL:
            raise AuthenticationCancelled("authentication was cancelled in the local window")
        if response.kind is AuthResponseKind.TIMEOUT:
            raise AuthenticationTimedOut("authentication window timed out")
        if prompt_kind is PromptKind.HOST_KEY:
            if response.kind is AuthResponseKind.REJECT:
                raise AuthenticationRejected("the host key was rejected in the local window")
            if response.kind is not AuthResponseKind.CONFIRM:
                raise AuthenticationProtocolError("host-key prompt requires a local decision")
            sink.submit(bytearray(b"yes"))
            return
        if response.kind is not AuthResponseKind.SECRET or response.secret is None:
            raise AuthenticationProtocolError("credential prompt requires local protected input")
        sink.submit(response.secret)

    @staticmethod
    def _finish_process(process: AuthProcess) -> None:
        try:
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    @staticmethod
    def _cancel_process(process: AuthProcess) -> None:
        process.terminate()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
