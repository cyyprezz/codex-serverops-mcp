from __future__ import annotations

import subprocess

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

    def respond(self, event: PromptEvent, sink: SecretInputSink) -> None:
        challenge = AuthChallengeServer(self.target, event, timeout=self.timeout)
        process: AuthProcess | None = None
        response: AuthResponse | None = None
        try:
            process = self.launcher.launch(challenge.descriptor)
            response = challenge.collect()
            self._apply_response(event.kind, response, sink)
        finally:
            challenge.close()
            if response is not None:
                response.clear()
            if process is not None:
                self._finish_process(process)

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
