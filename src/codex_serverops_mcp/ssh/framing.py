from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_SHELL_NONCE_VARIABLE = "_SERVEROPS_SHELL_NONCE"
_PARTIAL_LINE_LIMIT = 4_096


@dataclass(frozen=True, slots=True)
class CommandResult:
    output: str
    exit_code: int
    cwd: str
    truncated: bool = False


class FrameProtocolError(ValueError):
    """A token-correlated shell frame was present but structurally invalid."""


def new_token() -> str:
    return secrets.token_hex(16).upper()


def shell_bootstrap_wrapper(shell_nonce: str, token: str) -> str:
    """Initialize the non-exported original-shell guard and prove Bash control."""
    _validate_token(shell_nonce, "shell nonce")
    body = (
        "builtin unset PROMPT_COMMAND\n"
        "builtin export PS1='' PS2='' PS3='' PS4=''\n"
        f"builtin readonly {_SHELL_NONCE_VARIABLE}='{shell_nonce}'"
    )
    return command_wrapper(body, token, shell_nonce=shell_nonce)


def command_wrapper(
    command: str,
    token: str,
    *,
    shell_nonce: str | None = None,
) -> str:
    _validate_token(token, "token")
    if shell_nonce is not None:
        _validate_token(shell_nonce, "shell nonce")
    begin = f"__SERVEROPS_BEGIN_{token}__"
    body = command.rstrip("\r\n") or ":"
    return (
        "builtin command -p stty -echo intr '^]' >/dev/null 2>&1\n"
        f"builtin printf '\\n{begin}\\n'; {{\n"
        f"{body}\n"
        "}; _serverops_exit=$?\n"
        f"{_completion_wrapper(token, shell_nonce, '$_serverops_exit')}"
    )


def interrupt_recovery_wrapper(
    token: str,
    *,
    shell_nonce: str | None = None,
) -> str:
    _validate_token(token, "token")
    if shell_nonce is not None:
        _validate_token(shell_nonce, "shell nonce")
    return _completion_wrapper(token, shell_nonce, "130")


def _completion_wrapper(token: str, shell_nonce: str | None, exit_value: str) -> str:
    end = f"__SERVEROPS_END_{token}__"
    cwd = f"__SERVEROPS_CWD_{token}__"
    health = f"__SERVEROPS_HEALTH_{token}__"
    condition = "builtin command -p stty -echo intr '^]' >/dev/null 2>&1"
    if shell_nonce is not None:
        condition += f" && {_shell_health_condition(shell_nonce)}"
    result = ""
    if shell_nonce is not None:
        result += (
            f"builtin printf '\\n__SERVEROPS_DEBUG_{token}__\\n'\n"
            "builtin trap -p DEBUG\n"
            f"builtin printf '__SERVEROPS_DEBUG_END_{token}__\\n'\n"
            "builtin trap - DEBUG\n"
        )
    result += (
        f"if {condition}; then\n"
        f"  builtin printf '\\n{end}:%s\\n' \"{exit_value}\"\n"
        f"  builtin printf '{cwd}:'\n"
        "  builtin pwd\n"
    )
    if shell_nonce is not None:
        result += f'  builtin printf \'{health}:%s\\n\' "${{{_SHELL_NONCE_VARIABLE}}}"\n'
    return result + "fi\n"


def _shell_health_condition(shell_nonce: str) -> str:
    return (
        f"[[ ${{{_SHELL_NONCE_VARIABLE}-}} == '{shell_nonce}' ]]"
        f" && [[ $(builtin readonly -p {_SHELL_NONCE_VARIABLE} 2>/dev/null) == "
        f"*'{_SHELL_NONCE_VARIABLE}=\"{shell_nonce}\"'* ]]"
        " && [[ $(builtin enable -p printf 2>/dev/null) == 'enable printf' ]]"
        " && [[ $(builtin enable -p pwd 2>/dev/null) == 'enable pwd' ]]"
    )


def _validate_token(value: str, name: str) -> None:
    if "\n" in value or "\r" in value or not value.isalnum():
        raise ValueError(f"{name} must be a single alphanumeric value")


class CommandFrameParser:
    """Incrementally parse one bounded, line-delimited command frame."""

    def __init__(
        self,
        token: str,
        max_output_bytes: int = 1_048_576,
        *,
        shell_nonce: str | None = None,
    ) -> None:
        _validate_token(token, "token")
        if shell_nonce is not None:
            _validate_token(shell_nonce, "shell nonce")
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        self._begin = f"__SERVEROPS_BEGIN_{token}__"
        self._end_prefix = f"__SERVEROPS_END_{token}__:"
        self._cwd_prefix = f"__SERVEROPS_CWD_{token}__:"
        self._health_line = (
            None if shell_nonce is None else f"__SERVEROPS_HEALTH_{token}__:{shell_nonce}"
        )
        self._debug_begin = (
            None if shell_nonce is None else f"__SERVEROPS_DEBUG_{token}__"
        )
        self._debug_end = (
            None if shell_nonce is None else f"__SERVEROPS_DEBUG_END_{token}__"
        )
        self._scan = bytearray()
        self._output = bytearray()
        self._max_output_bytes = max_output_bytes
        self._started = False
        self._truncated = False
        self._done = False
        self._pending_exit: int | None = None
        self._pending_cwd: str | None = None
        self._pending_output_line: bytes | None = None
        self._in_debug_probe = False
        self._debug_probe_seen = shell_nonce is None

    def feed(self, data: bytes, *, final: bool = False) -> CommandResult | None:
        if self._done:
            raise RuntimeError("frame already completed")
        self._scan.extend(data)
        while True:
            newline = self._scan.find(b"\n")
            if newline < 0:
                self._bound_partial_line()
                if final:
                    raise FrameProtocolError("command frame ended before verified completion")
                return None
            raw_line = bytes(self._scan[: newline + 1])
            del self._scan[: newline + 1]
            result = self._consume_line(raw_line)
            if result is not None:
                return result

    def _consume_line(self, raw_line: bytes) -> CommandResult | None:
        line = raw_line[:-1].rstrip(b"\r").decode("utf-8", errors="replace")
        normalized = ANSI_ESCAPE.sub("", line)
        if not self._started:
            if normalized == self._begin:
                self._started = True
            elif normalized.startswith(self._begin):
                raise FrameProtocolError("command begin frame is malformed")
            return None

        if self._pending_exit is None:
            if self._in_debug_probe:
                if normalized == self._debug_end:
                    self._in_debug_probe = False
                    self._debug_probe_seen = True
                elif normalized:
                    raise FrameProtocolError("the Bash DEBUG trap changed during the command")
                return None
            if self._debug_begin is not None and normalized == self._debug_begin:
                self._flush_final_output_line()
                self._in_debug_probe = True
                return None
            if self._debug_begin is not None and normalized.startswith(self._debug_begin):
                raise FrameProtocolError("command DEBUG-probe frame is malformed")
            if normalized.startswith(self._end_prefix):
                if not self._debug_probe_seen:
                    raise FrameProtocolError("command DEBUG-probe frame is missing")
                exit_text = normalized[len(self._end_prefix) :]
                if re.fullmatch(r"-?\d+", exit_text) is None:
                    raise FrameProtocolError("command exit frame is malformed")
                self._flush_final_output_line()
                self._pending_exit = int(exit_text)
            else:
                if self._pending_output_line is not None:
                    self._store_output(self._pending_output_line)
                self._pending_output_line = raw_line
            return None

        if self._pending_cwd is None:
            if not normalized.startswith(self._cwd_prefix):
                raise FrameProtocolError("command cwd frame is missing after the exit frame")
            self._pending_cwd = normalized[len(self._cwd_prefix) :]
            if self._health_line is None:
                return self._complete()
            return None

        if normalized != self._health_line:
            raise FrameProtocolError("command shell-health frame is invalid")
        return self._complete()

    def _complete(self) -> CommandResult:
        assert self._pending_exit is not None
        assert self._pending_cwd is not None
        decoded_output = self._output.decode("utf-8", errors="replace")
        decoded_output = ANSI_ESCAPE.sub("", decoded_output)
        decoded_output = re.sub(r"\r+\n", "\n", decoded_output).replace("\r", "\n")
        self._done = True
        return CommandResult(
            output=decoded_output,
            exit_code=self._pending_exit,
            cwd=self._pending_cwd,
            truncated=self._truncated,
        )

    def _bound_partial_line(self) -> None:
        if not self._started or self._pending_exit is not None:
            if len(self._scan) > _PARTIAL_LINE_LIMIT:
                raise FrameProtocolError("command frame line exceeds the supported limit")
            return
        if len(self._scan) > _PARTIAL_LINE_LIMIT:
            if self._pending_output_line is not None:
                self._store_output(self._pending_output_line)
                self._pending_output_line = None
            flush = len(self._scan) - _PARTIAL_LINE_LIMIT
            self._store_output(bytes(self._scan[:flush]))
            del self._scan[:flush]

    def _store_output(self, data: bytes) -> None:
        if not data:
            return
        self._output.extend(data)
        overflow = len(self._output) - self._max_output_bytes
        if overflow > 0:
            del self._output[:overflow]
            self._truncated = True

    def _flush_final_output_line(self) -> None:
        line = self._pending_output_line
        self._pending_output_line = None
        if line is None:
            return
        nested_line_end = re.search(rb"\r+\n$", line)
        if nested_line_end is not None:
            line = line[: nested_line_end.start()]
        elif line.endswith(b"\n"):
            line = line[:-1]
        self._store_output(line)
