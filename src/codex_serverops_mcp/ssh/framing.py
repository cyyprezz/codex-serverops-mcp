from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


@dataclass(frozen=True, slots=True)
class CommandResult:
    output: str
    exit_code: int
    cwd: str
    truncated: bool = False


def new_token() -> str:
    return secrets.token_hex(16).upper()


def command_wrapper(command: str, token: str) -> str:
    if "\n" in token or "\r" in token or not token.isalnum():
        raise ValueError("token must be a single alphanumeric value")
    begin = f"__SERVEROPS_BEGIN_{token}__"
    end = f"__SERVEROPS_END_{token}__"
    cwd = f"__SERVEROPS_CWD_{token}__"
    body = command.rstrip("\r\n") or ":"
    return (
        f"printf '\\n{begin}\\n'; {{\n"
        f"{body}\n"
        "}; _serverops_exit=$?; "
        f"printf '\\n{end}:%s\\n' \"$_serverops_exit\"; "
        f"printf '{cwd}:%s\\n' \"$PWD\"\n"
    )


def interrupt_recovery_wrapper(token: str) -> str:
    if "\n" in token or "\r" in token or not token.isalnum():
        raise ValueError("token must be a single alphanumeric value")
    end = f"__SERVEROPS_END_{token}__"
    cwd = f"__SERVEROPS_CWD_{token}__"
    return (
        f"printf '\\n{end}:130\\n'; "
        f"printf '{cwd}:%s\\n' \"$PWD\"\n"
    )


class CommandFrameParser:
    """Incrementally parse one bounded command frame from combined PTY bytes."""

    def __init__(self, token: str, max_output_bytes: int = 1_048_576) -> None:
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        self._begin = f"__SERVEROPS_BEGIN_{token}__".encode()
        self._end_prefix = f"__SERVEROPS_END_{token}__:".encode()
        self._cwd_prefix = f"__SERVEROPS_CWD_{token}__:".encode()
        self._scan = bytearray()
        self._output = bytearray()
        self._max_output_bytes = max_output_bytes
        self._started = False
        self._truncated = False
        self._done = False

    def feed(self, data: bytes, *, final: bool = False) -> CommandResult | None:
        if self._done:
            raise RuntimeError("frame already completed")
        del final
        self._scan.extend(data)
        if not self._started:
            begin_index = self._scan.find(self._begin)
            if begin_index < 0:
                self._retain_marker_tail(self._begin)
                return None
            line_end = self._scan.find(b"\n", begin_index + len(self._begin))
            if line_end < 0:
                del self._scan[:begin_index]
                return None
            del self._scan[: line_end + 1]
            self._started = True

        end_index = self._scan.find(self._end_prefix)
        if end_index < 0:
            keep = len(self._end_prefix) + 16
            if len(self._scan) > keep:
                self._store_output(bytes(self._scan[:-keep]))
                del self._scan[:-keep]
            return None

        line_end = self._scan.find(b"\n", end_index + len(self._end_prefix))
        if line_end < 0:
            return None
        cwd_index = self._scan.find(self._cwd_prefix, line_end + 1)
        if cwd_index < 0:
            return None
        cwd_end = self._scan.find(b"\n", cwd_index + len(self._cwd_prefix))
        if cwd_end < 0:
            return None

        output = bytes(self._scan[:end_index])
        nested_line_end = re.search(rb"\r+\n$", output)
        if nested_line_end is not None:
            output = output[: nested_line_end.start()]
        elif output.endswith((b"\r", b"\n")):
            output = output[:-1]
        self._store_output(output)
        exit_text = bytes(self._scan[end_index + len(self._end_prefix) : line_end]).strip()
        try:
            exit_code = int(exit_text)
        except ValueError as exc:
            raise ValueError("invalid exit code in command frame") from exc
        cwd = bytes(self._scan[cwd_index + len(self._cwd_prefix) : cwd_end]).strip()
        decoded_output = self._output.decode("utf-8", errors="replace")
        decoded_output = ANSI_ESCAPE.sub("", decoded_output)
        decoded_output = re.sub(r"\r+\n", "\n", decoded_output).replace("\r", "\n")
        self._done = True
        return CommandResult(
            output=decoded_output,
            exit_code=exit_code,
            cwd=ANSI_ESCAPE.sub("", cwd.decode("utf-8", errors="replace")),
            truncated=self._truncated,
        )

    def _retain_marker_tail(self, marker: bytes) -> None:
        keep = len(marker) + 16
        if len(self._scan) > keep:
            del self._scan[:-keep]

    def _store_output(self, data: bytes) -> None:
        if not data:
            return
        self._output.extend(data)
        overflow = len(self._output) - self._max_output_bytes
        if overflow > 0:
            del self._output[:overflow]
            self._truncated = True
