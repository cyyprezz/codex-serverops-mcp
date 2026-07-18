from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from codex_serverops_mcp.auth.wire import MAX_AUTH_RESPONSE_BYTES
from codex_serverops_mcp.ssh.prompts import PromptEvent

from .errors import AuthenticationUnavailable


class SecretInputSink:
    """Single-use capability that zeroes a mutable auth response after terminal input."""

    def __init__(self, write: Callable[[bytes], None], *, newline: bytes) -> None:
        self._write = write
        self._newline = newline
        self._used = False

    @property
    def used(self) -> bool:
        return self._used

    def submit(self, response: bytearray) -> None:
        if self._used:
            raise RuntimeError("authentication response capability was already used")
        if not response or len(response) > MAX_AUTH_RESPONSE_BYTES:
            raise ValueError("authentication response has an invalid length")
        if b"\r" in response or b"\n" in response:
            raise ValueError("authentication response cannot contain a line ending")
        self._used = True
        try:
            self._write(bytes(response) + self._newline)
        finally:
            response[:] = b"\0" * len(response)


class AuthenticationCoordinator(Protocol):
    """Worker-local coordinator; implementations communicate directly with the auth UI."""

    def respond(self, event: PromptEvent, sink: SecretInputSink) -> None: ...


class UnavailableAuthenticationCoordinator:
    def respond(self, event: PromptEvent, sink: SecretInputSink) -> None:
        del event, sink
        raise AuthenticationUnavailable("no local authentication coordinator is configured")
