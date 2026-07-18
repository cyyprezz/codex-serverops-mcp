from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from codex_serverops_mcp.config import ServerProfile

from .errors import FileConflictError, RemoteFileError
from .patch import MAX_PATCH_BYTES, apply_unified_patch
from .shell import FileShellBuilder
from .wire import FileWireCommand, FileWireResponse, parse_file_response

MAX_REMOTE_PATH_BYTES = 4_096
MAX_WRITE_TEXT_BYTES = 131_072
MAX_QUERY_BYTES = 2_048
SHA256 = re.compile(r"^[0-9a-f]{64}$")

CommandRunner = Callable[[str, float | None], dict[str, object]]


@dataclass(slots=True)
class RemoteFileService:
    profile: ServerProfile
    command_runner: CommandRunner

    def read(self, action: str, payload: Mapping[str, object]) -> dict[str, object]:
        self._require_read()
        path = self._path(payload, "path")
        shell = FileShellBuilder(self.profile.allowed_roots)
        if action == "list":
            limit = self._integer(payload, "max_results", default=200, minimum=1, maximum=1_000)
            return self._list(self._run(shell.list_directory(path, limit)))
        if action == "stat":
            return self._stat(self._run(shell.stat(path)))
        if action == "hash":
            return self._hash(self._run(shell.hash(path)))
        if action == "read_text":
            byte_limit = self._integer(
                payload,
                "byte_limit",
                default=min(65_536, self.max_read_bytes),
                minimum=1,
                maximum=self.max_read_bytes,
            )
            start_line, end_line = self._line_range(payload)
            return self._read_text(
                self._run(shell.read_text(path, byte_limit, start_line, end_line)),
                start_line=start_line,
                end_line=end_line,
            )
        if action == "search_text":
            query = self._query(payload)
            limit = self._integer(payload, "max_results", default=100, minimum=1, maximum=500)
            return self._search(self._run(shell.search_text(path, query, limit)))
        raise ValueError(f"unsupported server_files action: {action}")

    def edit(self, action: str, payload: Mapping[str, object]) -> dict[str, object]:
        self._require_write()
        path = self._path(payload, "path")
        shell = FileShellBuilder(self.profile.allowed_roots)
        expected = self._expected_hash(payload)
        if action == "write_text":
            content = self._content(payload, "content")
            return self._write_result(
                self._run(shell.write_text(path, content.encode("utf-8"), expected))
            )
        if action == "apply_patch":
            patch = self._content(payload, "patch", maximum=MAX_PATCH_BYTES)
            return self._apply_patch(shell, path, patch, expected)
        if action == "mkdir":
            self._forbid(expected, "expected_sha256", action)
            response = self._run(shell.mkdir(path))
            return {"status": "created", "path": response.one("path")}
        if action == "rename":
            self._forbid(expected, "expected_sha256", action)
            destination = self._path(payload, "destination_path")
            response = self._run(shell.rename(path, destination))
            return {
                "status": "renamed",
                "source": response.one("source"),
                "destination": response.one("destination"),
            }
        if action == "remove":
            recursive = self._boolean(payload, "recursive", default=False)
            response = self._run(
                shell.remove(path, recursive=recursive, expected_sha256=expected)
            )
            return {"status": "removed", "path": response.one("path")}
        raise ValueError(f"unsupported server_file_edit action: {action}")

    @property
    def max_read_bytes(self) -> int:
        response_capacity = max(1, (self.profile.max_output_bytes - 2_048) * 3 // 4)
        return min(1_048_576, response_capacity)

    def _apply_patch(
        self,
        shell: FileShellBuilder,
        path: str,
        patch: str,
        expected: str | None,
    ) -> dict[str, object]:
        limit = min(MAX_WRITE_TEXT_BYTES + 1, self.max_read_bytes)
        current = self._read_text(
            self._run(shell.read_text(path, limit, None, None)),
            start_line=None,
            end_line=None,
        )
        if current["truncated"]:
            raise RemoteFileError(
                "file_too_large",
                "remote text exceeds the safe apply_patch size limit",
            )
        current_hash = str(current["sha256"])
        if expected is not None and expected != current_hash:
            raise FileConflictError("remote file does not match expected_sha256")
        updated = apply_unified_patch(str(current["content"]), patch)
        content = updated.encode("utf-8")
        if len(content) > MAX_WRITE_TEXT_BYTES:
            raise ValueError("patched text exceeds the 131072-byte write limit")
        return self._write_result(self._run(shell.write_text(path, content, current_hash)))

    def _run(self, command: FileWireCommand) -> FileWireResponse:
        result = self.command_runner(command.command, self.profile.command_timeout_seconds)
        status = result.get("status")
        if status == "outcome_unknown":
            raise RemoteFileError(
                "file_outcome_unknown",
                "connection ended before the remote file operation could be verified",
            )
        if status != "completed" or result.get("exit_code") != 0:
            raise RemoteFileError("file_command_failed", "remote file helper did not complete")
        if result.get("truncated") is True:
            raise RemoteFileError(
                "file_protocol_error",
                "remote file helper response was truncated",
            )
        output = result.get("output")
        if not isinstance(output, str):
            raise RemoteFileError("file_protocol_error", "remote file helper returned no text")
        return parse_file_response(output, command.token)

    @staticmethod
    def _list(response: FileWireResponse) -> dict[str, object]:
        entries = [
            {
                "name": name,
                "type": kind,
                "size": _nonnegative_integer(size, "size"),
                "modified_epoch": _nonnegative_integer(modified, "modified_epoch"),
                "mode": mode,
            }
            for name, kind, size, modified, mode in response.many("entry", width=5)
        ]
        return {
            "status": "completed",
            "path": response.one("path"),
            "entries": entries,
            "truncated": _wire_bool(response.one("truncated")),
        }

    @staticmethod
    def _stat(response: FileWireResponse) -> dict[str, object]:
        return {
            "status": "completed",
            "path": response.one("path"),
            "type": response.one("type"),
            "size": _nonnegative_integer(response.one("size"), "size"),
            "modified_epoch": _nonnegative_integer(
                response.one("modified_epoch"), "modified_epoch"
            ),
            "mode": response.one("mode"),
        }

    @staticmethod
    def _hash(response: FileWireResponse) -> dict[str, object]:
        digest = response.one("sha256")
        if not SHA256.fullmatch(digest):
            raise RemoteFileError("file_protocol_error", "remote SHA-256 is invalid")
        return {"status": "completed", "path": response.one("path"), "sha256": digest}

    @staticmethod
    def _read_text(
        response: FileWireResponse,
        *,
        start_line: int | None,
        end_line: int | None,
    ) -> dict[str, object]:
        digest = response.one("sha256")
        if not SHA256.fullmatch(digest):
            raise RemoteFileError("file_protocol_error", "remote SHA-256 is invalid")
        truncated = _wire_bool(response.one("truncated"))
        raw = response.one_bytes("content")
        text = _decode_remote_text(raw, truncated=truncated)
        result: dict[str, object] = {
            "status": "completed",
            "path": response.one("path"),
            "sha256": digest,
            "content": text,
            "bytes_returned": len(raw),
            "selected_bytes": _nonnegative_integer(
                response.one("selected_bytes"), "selected_bytes"
            ),
            "truncated": truncated,
        }
        if start_line is not None:
            result["start_line"] = start_line
            result["end_line"] = end_line
        return result

    @staticmethod
    def _search(response: FileWireResponse) -> dict[str, object]:
        matches = [
            {
                "path": path,
                "line": _positive_integer(line, "line"),
                "text": text,
            }
            for path, line, text in response.many("match", width=3)
        ]
        return {
            "status": "completed",
            "path": response.one("path"),
            "matches": matches,
            "truncated": _wire_bool(response.one("truncated")),
        }

    @staticmethod
    def _write_result(response: FileWireResponse) -> dict[str, object]:
        digest = response.one("sha256")
        if not SHA256.fullmatch(digest):
            raise RemoteFileError("file_protocol_error", "remote SHA-256 is invalid")
        return {
            "status": "created" if _wire_bool(response.one("created")) else "updated",
            "path": response.one("path"),
            "sha256": digest,
        }

    def _require_read(self) -> None:
        if not self.profile.allow_file_read:
            raise RemoteFileError("file_read_disabled", "structured file reads are disabled")

    def _require_write(self) -> None:
        if not self.profile.allow_file_write:
            raise RemoteFileError("file_write_disabled", "structured file writes are disabled")

    @staticmethod
    def _path(payload: Mapping[str, object], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError(f"{name} must be non-empty text without NUL")
        if len(value.encode("utf-8")) > MAX_REMOTE_PATH_BYTES:
            raise ValueError(f"{name} exceeds the 4096-byte limit")
        if any(ord(character) < 32 for character in value):
            raise ValueError(f"{name} contains a control character")
        return value

    @staticmethod
    def _content(
        payload: Mapping[str, object],
        name: str,
        *,
        maximum: int = MAX_WRITE_TEXT_BYTES,
    ) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or "\0" in value:
            raise ValueError(f"{name} must be text without NUL")
        if len(value.encode("utf-8")) > maximum:
            raise ValueError(f"{name} exceeds the {maximum}-byte limit")
        return value

    @staticmethod
    def _query(payload: Mapping[str, object]) -> str:
        query = RemoteFileService._content(payload, "query", maximum=MAX_QUERY_BYTES)
        if not query or any(ord(character) < 32 for character in query):
            raise ValueError("query must be non-empty single-line text")
        return query

    @staticmethod
    def _expected_hash(payload: Mapping[str, object]) -> str | None:
        value = payload.get("expected_sha256")
        if value is None:
            return None
        if not isinstance(value, str) or not SHA256.fullmatch(value.lower()):
            raise ValueError("expected_sha256 must be a 64-character hexadecimal digest")
        return value.lower()

    @staticmethod
    def _line_range(payload: Mapping[str, object]) -> tuple[int | None, int | None]:
        start = payload.get("start_line")
        end = payload.get("end_line")
        if start is None and end is None:
            return None, None
        if isinstance(start, bool) or not isinstance(start, int) or start < 1:
            raise ValueError("start_line must be a positive integer")
        if isinstance(end, bool) or not isinstance(end, int) or end < start:
            raise ValueError("end_line must be an integer at least start_line")
        if end - start > 100_000:
            raise ValueError("line range is too large")
        return start, end

    @staticmethod
    def _integer(
        payload: Mapping[str, object],
        name: str,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        value = payload.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} is outside the supported range")
        return value

    @staticmethod
    def _boolean(payload: Mapping[str, object], name: str, *, default: bool) -> bool:
        value = payload.get(name, default)
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be true or false")
        return value

    @staticmethod
    def _forbid(value: object | None, field_name: str, action: str) -> None:
        if value is not None:
            raise ValueError(f"{field_name} is not valid for {action}")


def _wire_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise RemoteFileError("file_protocol_error", "remote boolean field is invalid")


def _nonnegative_integer(value: str, name: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise RemoteFileError("file_protocol_error", f"remote {name} is invalid") from error
    if result < 0:
        raise RemoteFileError("file_protocol_error", f"remote {name} is invalid")
    return result


def _positive_integer(value: str, name: str) -> int:
    result = _nonnegative_integer(value, name)
    if result < 1:
        raise RemoteFileError("file_protocol_error", f"remote {name} is invalid")
    return result


def _decode_remote_text(content: bytes, *, truncated: bool) -> str:
    if b"\0" in content or any(byte < 32 and byte not in {9, 10, 13} for byte in content):
        raise RemoteFileError("binary_file", "remote file is not supported UTF-8 text")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        if truncated and error.reason == "unexpected end of data" and error.end == len(content):
            return content[: error.start].decode("utf-8")
        raise RemoteFileError("invalid_utf8", "remote file is not valid UTF-8 text") from error
