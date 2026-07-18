from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import suppress

from codex_serverops_mcp.ssh.framing import (
    CommandFrameParser,
    FrameProtocolError,
    command_wrapper,
    new_token,
)
from codex_serverops_mcp.terminal.contracts import TerminalProcess

from .control import REMOTE_VINTR_BYTE
from .errors import OutcomeUnknown, SessionLost
from .result import InteractiveRead, InteractiveStatus
from .state import SessionState, SessionStateMachine

MAX_INTERACTIVE_WRITE_BYTES = 65_536


class InteractiveTerminalController:
    """Raw terminal actions kept separate from completed-command framing."""

    def __init__(
        self,
        terminal: TerminalProcess,
        state: SessionStateMachine,
        read_and_handle_prompts: Callable[[float], bytes],
        *,
        shell_nonce: str,
    ) -> None:
        self._terminal = terminal
        self._state = state
        self._read_and_handle_prompts = read_and_handle_prompts
        self._shell_nonce = shell_nonce

    def start(self, command: str) -> InteractiveStatus:
        if not command or "\x00" in command:
            raise ValueError("interactive command must be non-empty text without NUL")
        self._state.require(SessionState.READY)
        start_cursor = self._terminal.output_cursor
        self._state.transition(SessionState.INTERACTIVE)
        try:
            self._terminal.write((command + "\r\n").encode("utf-8"))
        except BaseException:
            self._state.transition(
                SessionState.FAILED if self._terminal.running else SessionState.LOST
            )
            raise
        return InteractiveStatus(
            state=self._state.state,
            running=self._terminal.running,
            output_cursor=start_cursor,
        )

    def read(self, cursor: int, *, timeout: float = 0) -> InteractiveRead:
        self._state.require(SessionState.INTERACTIVE)
        self._read_and_handle_prompts(max(0, timeout))
        result = self._terminal.read(cursor)
        if not self._terminal.running:
            self._state.transition(SessionState.LOST)
            raise SessionLost("the SSH terminal closed during interactive operation")
        return InteractiveRead(
            output=result.data.decode("utf-8", errors="replace"),
            next_cursor=result.next_cursor,
            dropped_before_cursor=result.dropped_before_cursor,
            state=self._state.state,
        )

    def write(self, text: str) -> InteractiveStatus:
        self._state.require(SessionState.INTERACTIVE)
        data = text.encode("utf-8")
        if not data or len(data) > MAX_INTERACTIVE_WRITE_BYTES:
            raise ValueError("interactive input must contain 1-65536 UTF-8 bytes")
        self._terminal.write(data)
        return self.status()

    def interrupt(self) -> InteractiveStatus:
        self._state.require(SessionState.INTERACTIVE)
        self._terminal.write(REMOTE_VINTR_BYTE)
        return self.status()

    def resize(self, columns: int, rows: int) -> InteractiveStatus:
        self._state.require(SessionState.INTERACTIVE)
        self._terminal.resize(columns, rows)
        return self.status()

    def status(self) -> InteractiveStatus:
        self._state.require(SessionState.INTERACTIVE)
        return InteractiveStatus(
            state=self._state.state,
            running=self._terminal.running,
            output_cursor=self._terminal.output_cursor,
        )

    def close(self, *, timeout: float = 5) -> InteractiveStatus:
        self._state.require(SessionState.INTERACTIVE)
        self._terminal.write(REMOTE_VINTR_BYTE)
        time.sleep(0.2)
        token = new_token()
        parser = CommandFrameParser(
            token,
            max_output_bytes=4_096,
            shell_nonce=self._shell_nonce,
        )
        self._terminal.write(
            command_wrapper(":", token, shell_nonce=self._shell_nonce).encode("utf-8")
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self._read_and_handle_prompts(min(0.25, deadline - time.monotonic()))
            if data:
                try:
                    result = parser.feed(data)
                except FrameProtocolError as error:
                    self._lose_session()
                    raise OutcomeUnknown(
                        "Interactive shell recovery framing was invalid; the session was lost."
                    ) from error
                if result is not None:
                    if not self._terminal.running:
                        self._lose_session()
                        raise OutcomeUnknown(
                            "The shell ended during interactive recovery; the session was lost."
                        )
                    self._state.transition(SessionState.READY)
                    return InteractiveStatus(
                        state=self._state.state,
                        running=True,
                        output_cursor=self._terminal.output_cursor,
                    )
            if not self._terminal.running:
                self._lose_session()
                raise OutcomeUnknown(
                    "The SSH terminal closed before interactive recovery was verified."
                )
        self._lose_session()
        raise OutcomeUnknown(
            "Interactive control did not return to the original Bash shell; the session was lost."
        )

    def _lose_session(self) -> None:
        if self._state.state is SessionState.INTERACTIVE:
            self._state.transition(SessionState.LOST)
        if self._terminal.running:
            with suppress(Exception):
                self._terminal.terminate()
