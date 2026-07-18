from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from codex_serverops_mcp import WORKER_PROTOCOL_VERSION
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind

AUTH_REQUEST_ID = re.compile(r"^auth_[0-9a-f]{32}$")
AUTH_PROMPT_FIELDS = {
    "request_id",
    "profile_name",
    "display_name",
    "host",
    "port",
    "user",
    "prompt_kind",
    "prompt",
    "expires_at",
    "worker_protocol_version",
}


def _validate_text(value: str, field_name: str, *, maximum: int) -> None:
    if (
        not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} has an invalid value")


def _validate_prompt_text(value: str) -> None:
    if (
        not value
        or value != value.strip()
        or len(value) > 2_048
        or any(
            (ord(character) < 32 and character != "\n") or ord(character) == 127
            for character in value
        )
    ):
        raise ValueError("prompt has an invalid value")


@dataclass(frozen=True, slots=True)
class AuthTargetContext:
    profile_name: str
    display_name: str
    host: str
    port: int
    user: str

    def __post_init__(self) -> None:
        _validate_text(self.profile_name, "profile_name", maximum=64)
        _validate_text(self.display_name, "display_name", maximum=255)
        _validate_text(self.host, "host", maximum=255)
        _validate_text(self.user, "user", maximum=64)
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("port must be an integer from 1 through 65535")


@dataclass(frozen=True, slots=True)
class AuthPrompt:
    request_id: str
    target: AuthTargetContext
    kind: PromptKind
    prompt: str
    expires_at: float

    def __post_init__(self) -> None:
        if not AUTH_REQUEST_ID.fullmatch(self.request_id):
            raise ValueError("authentication request ID has an invalid format")
        if not isinstance(self.target, AuthTargetContext):
            raise ValueError("authentication target context is invalid")
        if not isinstance(self.kind, PromptKind):
            raise ValueError("authentication prompt kind is invalid")
        _validate_prompt_text(self.prompt)
        if (
            isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, int | float)
            or not math.isfinite(self.expires_at)
        ):
            raise ValueError("authentication expiry must be a finite timestamp")

    @classmethod
    def from_event(
        cls,
        request_id: str,
        target: AuthTargetContext,
        event: PromptEvent,
        *,
        expires_at: float,
    ) -> AuthPrompt:
        return cls(request_id, target, event.kind, event.prompt, expires_at)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> AuthPrompt:
        if set(payload) != AUTH_PROMPT_FIELDS:
            raise ValueError("authentication prompt fields are invalid")
        request_id = payload["request_id"]
        profile_name = payload["profile_name"]
        display_name = payload["display_name"]
        host = payload["host"]
        port = payload["port"]
        user = payload["user"]
        prompt_kind = payload["prompt_kind"]
        prompt = payload["prompt"]
        expires_at = payload["expires_at"]
        worker_protocol_version = payload["worker_protocol_version"]
        if not all(
            isinstance(value, str)
            for value in (
                request_id,
                profile_name,
                display_name,
                host,
                user,
                prompt_kind,
                prompt,
            )
        ):
            raise ValueError("authentication prompt text fields are invalid")
        if isinstance(port, bool) or not isinstance(port, int):
            raise ValueError("authentication prompt port is invalid")
        if isinstance(expires_at, bool) or not isinstance(expires_at, int | float):
            raise ValueError("authentication prompt expiry is invalid")
        if worker_protocol_version != WORKER_PROTOCOL_VERSION:
            raise ValueError("authentication worker protocol version is incompatible")
        return cls(
            request_id=request_id,
            target=AuthTargetContext(profile_name, display_name, host, port, user),
            kind=PromptKind(prompt_kind),
            prompt=prompt,
            expires_at=float(expires_at),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "profile_name": self.target.profile_name,
            "display_name": self.target.display_name,
            "host": self.target.host,
            "port": self.target.port,
            "user": self.target.user,
            "prompt_kind": self.kind.value,
            "prompt": self.prompt,
            "expires_at": self.expires_at,
            "worker_protocol_version": WORKER_PROTOCOL_VERSION,
        }
