from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .framing import ANSI_ESCAPE

READY_PROMPT = re.compile(r"(?:^|\n)bash-[0-9.]+[$#] ?")
HOST_KEY_PROMPT = re.compile(r"Are you sure you want to continue connecting.*?\?", re.I)
KEY_PASSPHRASE_PROMPT = re.compile(r"Enter passphrase for key .*?:", re.I)
SUDO_PROMPT = re.compile(r"\[sudo\] password for .*?:", re.I)
SUDO_PROMPT_TEXT = "[sudo] password for %u:"
PASSWORD_PROMPT = re.compile(r"(?:^|\n)[^\n]*password:", re.I)


class PromptKind(StrEnum):
    HOST_KEY = "host_key"
    PASSWORD = "password"
    KEY_PASSPHRASE = "key_passphrase"
    SUDO_PASSWORD = "sudo_password"


@dataclass(frozen=True, slots=True)
class PromptEvent:
    kind: PromptKind
    prompt: str


class PromptDetector:
    """Incrementally classify OpenSSH and sudo prompts without retaining an unbounded log."""

    def __init__(self, *, history_characters: int = 65_536) -> None:
        if history_characters < 1_024:
            raise ValueError("prompt history must be at least 1024 characters")
        self._history_characters = history_characters
        self._history = ""
        self._base_offset = 0
        self._seen_offsets: dict[PromptKind, int] = {}

    @property
    def ready(self) -> bool:
        return READY_PROMPT.search(self._history) is not None

    def feed(self, text: str) -> list[PromptEvent]:
        plain = ANSI_ESCAPE.sub("", text).replace("\r", "")
        self._history += plain
        if len(self._history) > self._history_characters:
            dropped = len(self._history) - self._history_characters
            self._history = self._history[dropped:]
            self._base_offset += dropped

        candidates: list[tuple[int, int, PromptKind, str]] = []
        patterns = (
            (PromptKind.HOST_KEY, HOST_KEY_PROMPT),
            (PromptKind.KEY_PASSPHRASE, KEY_PASSPHRASE_PROMPT),
            (PromptKind.SUDO_PASSWORD, SUDO_PROMPT),
            (PromptKind.PASSWORD, PASSWORD_PROMPT),
        )
        for kind, pattern in patterns:
            for match in pattern.finditer(self._history):
                if kind is PromptKind.PASSWORD and SUDO_PROMPT.search(match.group(0)):
                    continue
                absolute_end = self._base_offset + match.end()
                if absolute_end <= self._seen_offsets.get(kind, 0):
                    continue
                candidates.append(
                    (
                        self._base_offset + match.start(),
                        absolute_end,
                        kind,
                        match.group(0).strip(),
                    )
                )

        events: list[PromptEvent] = []
        for _start, absolute_end, kind, prompt in sorted(candidates):
            if absolute_end <= self._seen_offsets.get(kind, 0):
                continue
            self._seen_offsets[kind] = absolute_end
            events.append(PromptEvent(kind=kind, prompt=prompt[-500:]))
        return events
