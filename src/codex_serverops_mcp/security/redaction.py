from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_PREVIEW_BYTES = 512


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    redacted: bool
    truncated: bool


_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
            r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)\b(https?://)[^\s/@:]+:[^\s/@]+@"),
        r"\1[REDACTED]@",
    ),
    (
        re.compile(
            r"(?i)(\b(?:password|passwd|pwd|api[_-]?key|access[_-]?token|secret)"
            r"\s*(?:=|:)\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)(--(?:password|passwd|api-key|access-token|secret)\s+)"
            r"(?:\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    (
        re.compile(r"\b(?:sk|pk|rk)-(?:live|test)-[A-Za-z0-9_-]{12,}\b"),
        "[REDACTED_API_KEY]",
    ),
    (
        re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
        "[REDACTED_AWS_ACCESS_KEY]",
    ),
)


def redact_preview(text: str, *, max_bytes: int = DEFAULT_PREVIEW_BYTES) -> RedactionResult:
    if not isinstance(text, str):
        raise TypeError("redaction input must be text")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 16:
        raise ValueError("max_bytes must be an integer of at least 16")
    redacted = False
    value = text
    for pattern, replacement in _PATTERNS:
        value, count = pattern.subn(replacement, value)
        redacted = redacted or count > 0
    preview, truncated = _truncate_utf8(value, max_bytes)
    return RedactionResult(preview, redacted, truncated)


def _truncate_utf8(value: str, byte_limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_limit:
        return value, False
    suffix = "…"
    budget = byte_limit - len(suffix.encode("utf-8"))
    prefix = encoded[:budget]
    while prefix:
        try:
            return prefix.decode("utf-8") + suffix, True
        except UnicodeDecodeError as error:
            prefix = prefix[: error.start]
    return suffix, True
