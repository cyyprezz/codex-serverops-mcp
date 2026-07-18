from __future__ import annotations

import re
from dataclasses import dataclass, field
from threading import Lock

from codex_serverops_mcp.config import Authentication, ConnectionType, ServerProfile

from .prompts import PromptEvent, PromptKind

HOST_KEY_LIMIT = 2_048
CREDENTIAL_PROMPT_LIMIT = 500
HOST_KEY_QUESTION = re.compile(r"Are you sure you want to continue connecting.*?\?", re.I | re.S)
HOST_KEY_FINGERPRINT = re.compile(
    r"(?:ED25519|ECDSA|RSA|DSA).*?fingerprint is SHA256:[A-Za-z0-9+/]+",
    re.I | re.S,
)
KEY_PASSPHRASE = re.compile(r"Enter passphrase for key .+?:\s*$", re.I | re.S)
ACCOUNT_PASSWORD = re.compile(r"(?:^|\n)[^\n]*password:\s*$", re.I)


class PromptPolicyError(ValueError):
    pass


def connection_prompt_kinds(profile: ServerProfile) -> frozenset[PromptKind]:
    if profile.connection_type is ConnectionType.SSH_CONFIG:
        return frozenset(
            {PromptKind.HOST_KEY, PromptKind.PASSWORD, PromptKind.KEY_PASSPHRASE}
        )
    if profile.authentication is Authentication.INTERACTIVE_PASSWORD:
        return frozenset({PromptKind.HOST_KEY, PromptKind.PASSWORD})
    return frozenset({PromptKind.HOST_KEY, PromptKind.KEY_PASSPHRASE})


def classify_askpass_prompt(prompt: str) -> PromptEvent:
    if not isinstance(prompt, str):
        raise PromptPolicyError("OpenSSH Askpass prompt must be text")
    normalized = prompt.replace("\r\n", "\n").replace("\r", "\n").strip()
    if (
        not normalized
        or len(normalized) > HOST_KEY_LIMIT
        or any(
            (ord(character) < 32 and character != "\n") or ord(character) == 127
            for character in normalized
        )
    ):
        raise PromptPolicyError("OpenSSH Askpass prompt is invalid or oversized")
    if HOST_KEY_QUESTION.search(normalized):
        if (
            "The authenticity of host " not in normalized
            or HOST_KEY_FINGERPRINT.search(normalized) is None
        ):
            raise PromptPolicyError("host-key prompt omitted its algorithm or fingerprint notice")
        return PromptEvent(PromptKind.HOST_KEY, normalized)
    if len(normalized) > CREDENTIAL_PROMPT_LIMIT:
        raise PromptPolicyError("credential prompt is oversized")
    if KEY_PASSPHRASE.search(normalized):
        return PromptEvent(PromptKind.KEY_PASSPHRASE, normalized)
    if "[sudo]" not in normalized.casefold() and ACCOUNT_PASSWORD.search(normalized):
        return PromptEvent(PromptKind.PASSWORD, normalized)
    raise PromptPolicyError("OpenSSH Askpass prompt kind is not recognized")


@dataclass(slots=True)
class ConnectionPromptPolicy:
    allowed_kinds: frozenset[PromptKind]
    _host_key_answered: bool = False
    _credential_answered: bool = False
    _lock: Lock = field(default_factory=Lock, repr=False)

    @classmethod
    def from_profile(cls, profile: ServerProfile) -> ConnectionPromptPolicy:
        return cls(connection_prompt_kinds(profile))

    def authorize(self, event: PromptEvent) -> None:
        with self._lock:
            if event.kind not in self.allowed_kinds:
                raise PromptPolicyError(
                    f"{event.kind.value} is not allowed by the selected profile"
                )
            if self._credential_answered:
                raise PromptPolicyError("connection authentication is already complete")
            if event.kind is PromptKind.HOST_KEY and self._host_key_answered:
                raise PromptPolicyError("a host-key decision was already supplied")

    def record_answer(self, kind: PromptKind) -> None:
        with self._lock:
            if kind is PromptKind.HOST_KEY:
                if self._host_key_answered:
                    raise PromptPolicyError("a host-key decision was already supplied")
                self._host_key_answered = True
                return
            if kind not in {PromptKind.PASSWORD, PromptKind.KEY_PASSPHRASE}:
                raise PromptPolicyError("prompt kind is not a connection credential")
            if self._credential_answered:
                raise PromptPolicyError("connection authentication is already complete")
            self._credential_answered = True

