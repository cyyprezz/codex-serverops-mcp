from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import FileConflictError, RemoteFileError

HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?\n?$"
)
MAX_PATCH_BYTES = 131_072


@dataclass(frozen=True, slots=True)
class PatchHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


def apply_unified_patch(original: str, patch: str) -> str:
    if not isinstance(patch, str) or not patch or "\0" in patch:
        raise ValueError("patch must be non-empty text without NUL")
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ValueError("patch exceeds the 131072-byte limit")
    hunks = _parse_hunks(patch)
    source = original.splitlines(keepends=True)
    result: list[str] = []
    cursor = 0
    for hunk in hunks:
        target_index = hunk.old_start - 1 if hunk.old_count else hunk.old_start
        if target_index < cursor or target_index > len(source):
            raise FileConflictError("patch hunk starts outside the current remote text")
        result.extend(source[cursor:target_index])
        source_index = target_index
        consumed = 0
        produced = 0
        for line in _normalize_no_newline_markers(hunk.lines):
            prefix, value = line[0], line[1:]
            if prefix == " ":
                _require_source_line(source, source_index, value)
                result.append(value)
                source_index += 1
                consumed += 1
                produced += 1
            elif prefix == "-":
                _require_source_line(source, source_index, value)
                source_index += 1
                consumed += 1
            elif prefix == "+":
                result.append(value)
                produced += 1
            else:  # pragma: no cover - parser already rejects this
                raise RemoteFileError("patch_invalid", "patch hunk line is invalid")
        if consumed != hunk.old_count or produced != hunk.new_count:
            raise RemoteFileError("patch_invalid", "patch hunk line counts do not match header")
        cursor = source_index
    result.extend(source[cursor:])
    return "".join(result)


def _parse_hunks(patch: str) -> tuple[PatchHunk, ...]:
    lines = patch.splitlines(keepends=True)
    hunks: list[PatchHunk] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(("--- ", "+++ ", "diff ", "index ")) or not line.strip():
            index += 1
            continue
        match = HUNK_HEADER.fullmatch(line)
        if match is None:
            raise RemoteFileError("patch_invalid", "patch contains unsupported text outside a hunk")
        old_start = int(match.group(1))
        old_count = int(match.group(2) or 1)
        new_start = int(match.group(3))
        new_count = int(match.group(4) or 1)
        index += 1
        hunk_lines: list[str] = []
        while index < len(lines) and HUNK_HEADER.fullmatch(lines[index]) is None:
            candidate = lines[index]
            if candidate.startswith((" ", "+", "-", "\\ No newline at end of file")):
                hunk_lines.append(candidate)
                index += 1
                continue
            break
        hunks.append(PatchHunk(old_start, old_count, new_start, new_count, tuple(hunk_lines)))
    if not hunks:
        raise RemoteFileError("patch_invalid", "patch contains no unified-diff hunks")
    return tuple(hunks)


def _normalize_no_newline_markers(lines: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for line in lines:
        if line.startswith("\\ No newline at end of file"):
            if not normalized:
                raise RemoteFileError("patch_invalid", "orphan no-newline marker")
            normalized[-1] = normalized[-1].removesuffix("\n")
            continue
        if not line or line[0] not in {" ", "+", "-"}:
            raise RemoteFileError("patch_invalid", "patch hunk line is invalid")
        normalized.append(line)
    return tuple(normalized)


def _require_source_line(source: list[str], index: int, expected: str) -> None:
    if index >= len(source) or source[index] != expected:
        raise FileConflictError("patch context does not match the current remote text")
