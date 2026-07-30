from __future__ import annotations

import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic, sleep

from codex_serverops_mcp.ssh.framing import (
    ANSI_ESCAPE,
    CommandFrameParser,
    CommandResult,
    FrameProtocolError,
    command_wrapper,
    interrupt_recovery_wrapper,
    new_token,
)
from codex_serverops_mcp.terminal.conpty import ConPtyProcess

PromptProvider = Callable[[str, str], str]


class SpikeTimeout(RuntimeError):
    pass


class OutcomeUnknown(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PromptEvent:
    kind: str
    prompt: str


READY_PROMPT = re.compile(r"bash-[0-9.]+[$#] ?")
HOST_KEY_PROMPT = re.compile(r"Are you sure you want to continue connecting.*?\?", re.I)
KEY_PASSPHRASE_PROMPT = re.compile(r"Enter passphrase for key .*?:", re.I)
SUDO_PROMPT = re.compile(r"\[sudo\] password for .*?:", re.I)
PASSWORD_PROMPT = re.compile(r"(?:^|\n)[^\n]*password:", re.I)


def _plain(text: str) -> str:
    return ANSI_ESCAPE.sub("", text).replace("\r", "")


class SshSpikeSession:
    """One stateful OpenSSH process hosted in ConPTY."""

    def __init__(
        self, *, max_output_bytes: int = 2_097_152, pty_backend: str = "conpty"
    ) -> None:
        self.terminal = ConPtyProcess(
            max_output_bytes=max_output_bytes, backend=pty_backend
        )
        self._cursor = 0
        self._prompt_offsets: dict[str, int] = {}
        self._history = ""
        self._ready = False
        self._active_token: str | None = None
        self._active_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.terminal.running

    @property
    def transcript_tail(self) -> str:
        return _plain(self._history)[-2_000:]

    def open(
        self,
        ssh_arguments: Sequence[str],
        prompt_provider: PromptProvider,
        *,
        timeout: float = 20,
    ) -> None:
        self.terminal.start(ssh_arguments)
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            self._read_and_handle_prompts(prompt_provider, min(0.25, deadline - monotonic()))
            if READY_PROMPT.search(_plain(self._history)):
                self._ready = True
                self.terminal.write(
                    b"stty -echo intr '^]'; "
                    b"builtin unset PROMPT_COMMAND PS0; "
                    b"builtin export PS1='' PS2='' PS3='' PS4=''; "
                    b"builtin readonly PROMPT_COMMAND='' PS0='' "
                    b"PS1='' PS2='' PS3='' PS4=''\r\n"
                )
                self._drain_for(0.2, prompt_provider)
                return
            if not self.terminal.running:
                raise RuntimeError(
                    "OpenSSH exited before a Bash prompt was reached:\n"
                    f"{self.transcript_tail}"
                )
        raise SpikeTimeout("timed out waiting for the authenticated Bash prompt")

    def execute(
        self,
        command: str,
        prompt_provider: PromptProvider,
        *,
        timeout: float = 20,
    ) -> CommandResult:
        if not self._ready or not self.terminal.running:
            raise RuntimeError("SSH session is not ready")
        token = new_token()
        parser = CommandFrameParser(token)
        with self._active_lock:
            if self._active_token is not None:
                raise RuntimeError("another command is already active")
            self._active_token = token
        try:
            self.terminal.write(command_wrapper(command, token).encode("utf-8"))
            deadline = monotonic() + timeout
            while monotonic() < deadline:
                data = self._read_and_handle_prompts(
                    prompt_provider, min(0.25, deadline - monotonic())
                )
                if data:
                    result = parser.feed(data)
                    if result is not None:
                        return result
                if not self.terminal.running:
                    try:
                        final = parser.feed(b"", final=True)
                    except FrameProtocolError as error:
                        raise OutcomeUnknown(
                            "The connection ended before command completion could be verified."
                        ) from error
                    if final is not None:
                        return final
                    raise OutcomeUnknown(
                        "The connection ended before command completion could be verified."
                    )
            raise SpikeTimeout(f"command did not complete within {timeout:.1f} seconds")
        finally:
            with self._active_lock:
                self._active_token = None

    def interrupt(self) -> None:
        # ConPTY consumes the local Ctrl+C byte before Windows OpenSSH can
        # reliably forward it. The session therefore remaps the remote VINTR
        # character to Ctrl+] and sends that byte to produce the same SIGINT.
        with self._active_lock:
            token = self._active_token
        if token is None:
            raise RuntimeError("there is no active command to interrupt")
        self.terminal.write(b"\x1d")
        # VINTR normally flushes pending terminal input. Wait before queueing a
        # recovery frame in the returned interactive shell.
        sleep(0.2)
        self.terminal.write(interrupt_recovery_wrapper(token).encode("utf-8"))

    def raw_write(self, text: str) -> None:
        self.terminal.write(text.encode("utf-8"))

    def read_new(self, timeout: float = 0) -> str:
        result = self.terminal.wait_for_data(self._cursor, timeout)
        self._cursor = result.next_cursor
        text = result.data.decode("utf-8", errors="replace")
        self._history += text
        return text

    def close(self) -> None:
        if self.terminal.running:
            try:
                self.terminal.write(b"exit\r\n")
                self.terminal.wait(2)
            except Exception:
                self.terminal.terminate()
        self.terminal.close()
        self._ready = False

    def _read_and_handle_prompts(
        self, prompt_provider: PromptProvider, timeout: float
    ) -> bytes:
        result = self.terminal.wait_for_data(self._cursor, max(0, timeout))
        self._cursor = result.next_cursor
        data = result.data
        if not data:
            return b""
        text = data.decode("utf-8", errors="replace")
        self._history += text
        plain = _plain(self._history)
        prompt_patterns = (
            ("host_key", HOST_KEY_PROMPT),
            ("key_passphrase", KEY_PASSPHRASE_PROMPT),
            ("sudo_password", SUDO_PROMPT),
            ("password", PASSWORD_PROMPT),
        )
        for kind, pattern in prompt_patterns:
            matches = list(pattern.finditer(plain))
            if not matches:
                continue
            match = matches[-1]
            if match.end() <= self._prompt_offsets.get(kind, 0):
                continue
            # A sudo prompt also contains "password:" and must be classified only once.
            if kind == "password" and SUDO_PROMPT.search(match.group(0)):
                continue
            response = prompt_provider(kind, match.group(0))
            newline = (
                "\r"
                if kind == "sudo_password" or self.terminal.backend_name == "winpty"
                else "\r\n"
            )
            self.terminal.write((response + newline).encode("utf-8"))
            self._prompt_offsets[kind] = match.end()
            if kind == "sudo_password":
                self._prompt_offsets["password"] = max(
                    self._prompt_offsets.get("password", 0), match.end()
                )
        return data

    def _drain_for(self, seconds: float, prompt_provider: PromptProvider) -> None:
        deadline = monotonic() + seconds
        while monotonic() < deadline:
            self._read_and_handle_prompts(prompt_provider, deadline - monotonic())
