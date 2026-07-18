from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress

from codex_serverops_mcp.ssh.framing import (
    CommandFrameParser,
    FrameProtocolError,
    command_wrapper,
    interrupt_recovery_wrapper,
    new_token,
    shell_bootstrap_wrapper,
)
from codex_serverops_mcp.ssh.prompts import PromptDetector, PromptKind
from codex_serverops_mcp.terminal.contracts import TerminalProcess

from .authentication import (
    AuthenticationCoordinator,
    SecretInputSink,
    UnavailableAuthenticationCoordinator,
)
from .control import REMOTE_VINTR_BYTE
from .errors import CommandTimedOut, OutcomeUnknown, SessionError, SessionLost
from .interactive import InteractiveTerminalController
from .result import ExecutionResult
from .state import SessionState, SessionStateMachine

COMMAND_INPUT_CHUNK_CHARACTERS = 512
COMMAND_INPUT_FLOW_DELAY_SECONDS = 0.01
SHELL_BOOTSTRAP_TIMEOUT_SECONDS = 5.0
RECOVERY_TIMEOUT_SECONDS = 5.0
def _default_terminal(max_output_bytes: int) -> TerminalProcess:
    from codex_serverops_mcp.terminal.conpty import ConPtyProcess

    return ConPtyProcess(max_output_bytes=max_output_bytes, backend="conpty")


class StatefulSshSession:
    """Own one OpenSSH terminal and enforce the product session state contract."""

    def __init__(
        self,
        *,
        terminal: TerminalProcess | None = None,
        terminal_factory: Callable[[int], TerminalProcess] = _default_terminal,
        authenticator: AuthenticationCoordinator | None = None,
        max_output_bytes: int = 2_097_152,
    ) -> None:
        self.terminal = terminal or terminal_factory(max_output_bytes)
        self.authenticator = authenticator or UnavailableAuthenticationCoordinator()
        self.max_output_bytes = max_output_bytes
        self.state = SessionStateMachine()
        self._detector = PromptDetector()
        self._cursor = 0
        self._active_token: str | None = None
        self._active_lock = threading.Lock()
        self._shell_nonce = new_token()
        self.interactive = InteractiveTerminalController(
            self.terminal,
            self.state,
            self._read_and_handle_prompts,
            shell_nonce=self._shell_nonce,
        )

    def open(
        self,
        ssh_arguments: Sequence[str],
        *,
        timeout: float = 20,
        allow_sudo_prompt: bool = False,
        sudo_prompt_token: str | None = None,
        environment: Mapping[str, str] | None = None,
        failure_check: Callable[[], None] | None = None,
    ) -> None:
        self.state.require(SessionState.CREATED)
        if allow_sudo_prompt != (sudo_prompt_token is not None):
            raise ValueError(
                "startup sudo authentication requires one operation-bound prompt token"
            )
        self.state.transition(SessionState.STARTING)
        try:
            child_environment = dict(os.environ)
            if environment is not None:
                child_environment.update(environment)
            try:
                self.terminal.start(ssh_arguments, environment=child_environment)
            finally:
                child_environment.clear()
            allowed_prompts = (
                frozenset({PromptKind.SUDO_PASSWORD})
                if allow_sudo_prompt
                else frozenset()
            )
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if failure_check is not None:
                    failure_check()
                self._read_and_handle_prompts(
                    min(0.25, deadline - time.monotonic()),
                    allowed_prompt_kinds=allowed_prompts,
                    sudo_prompt_token=sudo_prompt_token,
                )
                if self._detector.ready:
                    if failure_check is not None:
                        failure_check()
                    self._initialize_shell(
                        timeout=min(
                            SHELL_BOOTSTRAP_TIMEOUT_SECONDS,
                            max(0.1, deadline - time.monotonic()),
                        ),
                        failure_check=failure_check,
                    )
                    self.state.transition(SessionState.READY)
                    return
                if not self.terminal.running:
                    self.state.transition(SessionState.FAILED)
                    raise SessionLost("OpenSSH exited before the Bash prompt was reached")
            self.state.transition(SessionState.FAILED)
            raise SessionError("timed out waiting for the authenticated Bash prompt")
        except BaseException:
            if self.terminal.running:
                with suppress(Exception):
                    self.terminal.terminate()
            if self.state.state in {SessionState.STARTING, SessionState.AUTHENTICATION_REQUIRED}:
                self.state.transition(SessionState.FAILED)
            raise

    def execute(
        self,
        command: str,
        *,
        timeout: float = 60,
        allow_sudo_prompt: bool = False,
        sudo_prompt_token: str | None = None,
    ) -> ExecutionResult:
        if not command or "\x00" in command:
            raise ValueError("command must be non-empty text without NUL")
        if allow_sudo_prompt != (sudo_prompt_token is not None):
            raise ValueError(
                "sudo authentication requires one operation-bound prompt token"
            )
        self.state.require(SessionState.READY)
        token = new_token()
        parser = CommandFrameParser(
            token,
            max_output_bytes=self.max_output_bytes,
            shell_nonce=self._shell_nonce,
        )
        self._activate_command(token)
        self.state.transition(SessionState.EXECUTING)
        started = time.monotonic()
        try:
            self._write_command(
                command_wrapper(command, token, shell_nonce=self._shell_nonce)
            )
            allowed_prompts = (
                frozenset({PromptKind.SUDO_PASSWORD})
                if allow_sudo_prompt
                else frozenset()
            )
            deadline = started + timeout

            def preserve_remote_timeout(authentication_seconds: float) -> None:
                nonlocal deadline
                deadline += authentication_seconds

            while time.monotonic() < deadline:
                data = self._read_and_handle_prompts(
                    min(0.25, deadline - time.monotonic()),
                    allowed_prompt_kinds=allowed_prompts,
                    sudo_prompt_token=sudo_prompt_token,
                    authentication_completed=preserve_remote_timeout,
                )
                if data:
                    try:
                        result = parser.feed(data)
                    except FrameProtocolError as error:
                        self._lose_executing_session()
                        raise OutcomeUnknown(
                            "Shell framing became invalid after command delivery; "
                            "the command outcome is unknown."
                        ) from error
                    if result is not None:
                        if not self.terminal.running:
                            self._lose_executing_session()
                            raise OutcomeUnknown(
                                "The shell ended after command delivery; the command outcome "
                                "and reusable session state cannot be trusted."
                            )
                        self.state.transition(SessionState.READY)
                        return ExecutionResult(
                            output=result.output,
                            exit_code=result.exit_code,
                            cwd=result.cwd,
                            truncated=result.truncated,
                            duration_ms=round((time.monotonic() - started) * 1_000),
                        )
                if not self.terminal.running:
                    with suppress(FrameProtocolError):
                        parser.feed(b"", final=True)
                    self._lose_executing_session()
                    raise OutcomeUnknown(
                        "The connection ended before command completion could be verified."
                    )
            self._send_interrupt(token)
            try:
                recovered = self._wait_for_recovery(
                    parser,
                    timeout=RECOVERY_TIMEOUT_SECONDS,
                    allowed_prompt_kinds=allowed_prompts,
                )
            except FrameProtocolError as error:
                self._lose_executing_session()
                raise OutcomeUnknown(
                    "The command timed out and recovery framing was invalid; the outcome "
                    "is unknown."
                ) from error
            if recovered and self.terminal.running:
                self.state.transition(SessionState.READY)
                raise CommandTimedOut(f"command exceeded its {timeout:.1f}-second timeout")
            self._lose_executing_session()
            raise OutcomeUnknown(
                "The command timed out and shell recovery could not be verified; "
                "the outcome is unknown."
            )
        except BaseException:
            if self.state.state is SessionState.EXECUTING:
                self.state.transition(
                    SessionState.FAILED if self.terminal.running else SessionState.LOST
                )
            raise
        finally:
            self._clear_command(token)

    def interrupt(self) -> None:
        self.state.require(SessionState.EXECUTING)
        with self._active_lock:
            token = self._active_token
        if token is None:
            raise SessionError("there is no active command to interrupt")
        self._send_interrupt(token)

    def close(self) -> None:
        if not self.state.begin_close():
            return
        try:
            if self.terminal.running:
                try:
                    self.terminal.write(b"exit\r\n")
                    if self.terminal.wait(2) is None:
                        self.terminal.terminate()
                except Exception:
                    self.terminal.terminate()
        finally:
            self.terminal.close()
            self.state.transition(SessionState.CLOSED)

    def _read_and_handle_prompts(
        self,
        timeout: float,
        *,
        allowed_prompt_kinds: frozenset[PromptKind] = frozenset(),
        sudo_prompt_token: str | None = None,
        authentication_completed: Callable[[float], None] | None = None,
    ) -> bytes:
        result = self.terminal.wait_for_data(self._cursor, max(0, timeout))
        self._cursor = result.next_cursor
        data = result.data
        if not data:
            return b""
        text = data.decode("utf-8", errors="replace")
        for event in self._detector.feed(text):
            if event.kind not in allowed_prompt_kinds:
                continue
            if (
                event.kind is PromptKind.SUDO_PASSWORD
                and sudo_prompt_token is not None
                and sudo_prompt_token not in event.prompt
            ):
                continue
            self.state.begin_authentication()
            authentication_started = time.monotonic()
            newline = b"\r" if self.terminal.backend_name == "winpty" else b"\r\n"
            sink = SecretInputSink(self.terminal.write, newline=newline)
            try:
                self.authenticator.respond(event, sink)
                if not sink.used:
                    raise SessionError("authentication coordinator returned without a response")
            except BaseException:
                if self.terminal.running:
                    self.terminal.terminate()
                self.state.transition(SessionState.FAILED)
                raise
            self.state.finish_authentication()
            if authentication_completed is not None:
                authentication_completed(time.monotonic() - authentication_started)
        return data

    def _initialize_shell(
        self,
        *,
        timeout: float,
        failure_check: Callable[[], None] | None = None,
    ) -> None:
        token = new_token()
        parser = CommandFrameParser(
            token,
            max_output_bytes=4_096,
            shell_nonce=self._shell_nonce,
        )
        self._write_command(shell_bootstrap_wrapper(self._shell_nonce, token))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if failure_check is not None:
                failure_check()
            data = self._read_and_handle_prompts(min(0.25, deadline - time.monotonic()))
            if data:
                try:
                    result = parser.feed(data)
                except FrameProtocolError as error:
                    raise SessionError("the Bash bootstrap frame was invalid") from error
                if result is not None:
                    if not self.terminal.running:
                        raise SessionLost("OpenSSH exited during Bash bootstrap")
                    if result.exit_code != 0:
                        raise SessionError("the Bash bootstrap command failed")
                    return
            if not self.terminal.running:
                raise SessionLost("OpenSSH exited during Bash bootstrap")
        raise SessionError("timed out while verifying control of the original Bash shell")

    def _activate_command(self, token: str) -> None:
        with self._active_lock:
            if self._active_token is not None:
                raise SessionError("another command is already active")
            self._active_token = token

    def _write_command(self, wrapped: str) -> None:
        if len(wrapped) <= COMMAND_INPUT_CHUNK_CHARACTERS:
            self.terminal.write(wrapped.encode("utf-8"))
            return
        pending = ""
        for line in wrapped.splitlines(keepends=True):
            while len(line) > COMMAND_INPUT_CHUNK_CHARACTERS:
                if pending:
                    self._write_command_chunk(pending)
                    pending = ""
                self._write_command_chunk(line[:COMMAND_INPUT_CHUNK_CHARACTERS])
                line = line[COMMAND_INPUT_CHUNK_CHARACTERS:]
            if pending and len(pending) + len(line) > COMMAND_INPUT_CHUNK_CHARACTERS:
                self._write_command_chunk(pending)
                pending = ""
            pending += line
        if pending:
            self.terminal.write(pending.encode("utf-8"))

    def _write_command_chunk(self, chunk: str) -> None:
        self.terminal.write(chunk.encode("utf-8"))
        time.sleep(COMMAND_INPUT_FLOW_DELAY_SECONDS)

    def _clear_command(self, token: str) -> None:
        with self._active_lock:
            if self._active_token == token:
                self._active_token = None

    def _send_interrupt(self, token: str) -> None:
        self.terminal.write(REMOTE_VINTR_BYTE)
        time.sleep(0.2)
        self.terminal.write(
            interrupt_recovery_wrapper(token, shell_nonce=self._shell_nonce).encode("utf-8")
        )

    def _wait_for_recovery(
        self,
        parser: CommandFrameParser,
        *,
        timeout: float,
        allowed_prompt_kinds: frozenset[PromptKind],
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self._read_and_handle_prompts(
                min(0.25, deadline - time.monotonic()),
                allowed_prompt_kinds=allowed_prompt_kinds,
            )
            if data and parser.feed(data) is not None:
                return True
            if not self.terminal.running:
                return False
        return False

    def _lose_executing_session(self) -> None:
        if self.state.state is SessionState.EXECUTING:
            self.state.transition(SessionState.LOST)
        if self.terminal.running:
            with suppress(Exception):
                self.terminal.terminate()
