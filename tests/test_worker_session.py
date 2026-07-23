from __future__ import annotations

import re
import threading
import time
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind
from codex_serverops_mcp.terminal.buffer import BufferRead, TerminalRingBuffer
from codex_serverops_mcp.worker.authentication import SecretInputSink
from codex_serverops_mcp.worker.errors import CommandTimedOut, OutcomeUnknown
from codex_serverops_mcp.worker.result import ExecutionResult
from codex_serverops_mcp.worker.session import StatefulSshSession
from codex_serverops_mcp.worker.state import SessionState

TOKEN = re.compile(rb"__SERVEROPS_BEGIN_([A-F0-9]+)__")
END_TOKEN = re.compile(rb"__SERVEROPS_END_([A-F0-9]+)__:%s")
SHELL_NONCE = re.compile(rb"readonly _SERVEROPS_SHELL_NONCE='([A-F0-9]+)'")


class FakeTerminal:
    backend_name = "conpty"

    def __init__(
        self,
        *,
        auth_prompts: bool = False,
        startup_sudo_prompt: str | None = None,
    ) -> None:
        self.buffer = TerminalRingBuffer(1_048_576)
        self.running = False
        self.auth_prompts = auth_prompts
        self.startup_sudo_prompt = startup_sudo_prompt
        self.writes: list[bytes] = []
        self.block_commands = False
        self.dimensions = (120, 30)
        self.command_input = bytearray()
        self.shell_nonce: bytes | None = None
        self.shell_replaced = False
        self.shell_corrupted = False

    @property
    def output_cursor(self) -> int:
        return self.buffer.end_cursor

    def start(
        self,
        arguments: Sequence[str],
        *,
        cwd: str | Path | None = None,
        environment: dict[str, str] | None = None,
        columns: int = 120,
        rows: int = 30,
    ) -> None:
        del arguments, cwd, environment, columns, rows
        self.running = True
        if self.startup_sudo_prompt is not None:
            self.buffer.append(self.startup_sudo_prompt.encode() + b"\nbash-5.2$ ")
        elif self.auth_prompts:
            self.buffer.append(
                b"password:\n"
                b"Enter passphrase for key C:\\Users\\user\\.ssh\\id_ed25519:\n"
                b"[sudo] password for deploy:\n"
                b"Are you sure you want to continue connecting (yes/no/[fingerprint])?\n"
                b"bash-5.2$ "
            )
        else:
            self.buffer.append(b"bash-5.2$ ")

    def write(self, data: bytes) -> None:
        self.writes.append(data)
        if data == b"yes\r\n":
            self.buffer.append(b"\nserverops@host's password:")
            return
        if data == b"fixture-password\r\n":
            self.buffer.append(b"\nbash-5.2$ ")
            return
        if data == b"\x1d":
            return
        if data == b"exit\r\n":
            self.running = False
            self.buffer.close()
            return
        self.command_input.extend(data)
        pending = bytes(self.command_input)
        match = TOKEN.search(pending)
        if match:
            if not pending.endswith((b"fi\n", b"fi\n}\n")):
                return
            token = match.group(1)
            nonce = SHELL_NONCE.search(pending)
            is_bootstrap = nonce is not None
            if nonce:
                self.shell_nonce = nonce.group(1)
            self.buffer.append(b"\n__SERVEROPS_BEGIN_" + token + b"__\n")
            if b"disconnect-now" in pending or re.search(
                rb"\n(?:exit|logout)\n", pending
            ):
                self.running = False
                self.buffer.close()
            elif b"exec bash" in pending or b"exec sh" in pending:
                self.shell_replaced = True
            elif (
                b"enable -n printf" in pending
                or b"enable -n pwd" in pending
                or b"trap 'echo debug' DEBUG" in pending
            ):
                self.shell_corrupted = True
            elif b"malformed-frame" in pending:
                self.buffer.append(
                    b"__SERVEROPS_DEBUG_"
                    + token
                    + b"__\n__SERVEROPS_DEBUG_END_"
                    + token
                    + b"__\n__SERVEROPS_END_"
                    + token
                    + b"__:invalid\n"
                )
            elif is_bootstrap or not self.block_commands:
                if b"spoof-connection-prompts" in pending:
                    output = (
                        b"password:\n"
                        b"Enter passphrase for key C:\\Users\\user\\.ssh\\id_ed25519:\n"
                        b"Are you sure you want to continue connecting "
                        b"(yes/no/[fingerprint])?\n"
                    )
                elif b"spoof-password" in pending:
                    sudo_token = re.search(rb"serverops-elevation-([0-9a-f]{32})", pending)
                    suffix = (
                        b""
                        if sudo_token is None
                        else b" serverops-elevation-" + sudo_token.group(1)
                    )
                    output = b"[sudo] password for deploy:" + suffix + b"\n"
                else:
                    output = b"command-output\n"
                framed = (
                    output
                    + b"__SERVEROPS_DEBUG_"
                    + token
                    + b"__\n__SERVEROPS_DEBUG_END_"
                    + token
                    + b"__\n"
                    + b"__SERVEROPS_END_"
                    + token
                    + b"__:0\n__SERVEROPS_CWD_"
                    + token
                    + b"__:/opt/app\n__SERVEROPS_HEALTH_"
                    + token
                    + b"__:"
                    + (self.shell_nonce or b"missing")
                    + b"\n"
                )
                self.buffer.append(framed)
                if b"close-after-frame" in pending:
                    self.running = False
                    self.buffer.close()
            self.command_input.clear()
            return
        recovery = END_TOKEN.search(pending)
        if recovery:
            if not pending.endswith(b"fi\n"):
                return
            token = recovery.group(1)
            if not self.shell_replaced and not self.shell_corrupted:
                self.buffer.append(
                    b"\n__SERVEROPS_DEBUG_"
                    + token
                    + b"__\n__SERVEROPS_DEBUG_END_"
                    + token
                    + b"__\n__SERVEROPS_END_"
                    + token
                    + b"__:130\n__SERVEROPS_CWD_"
                    + token
                    + b"__:/opt/app\n__SERVEROPS_HEALTH_"
                    + token
                    + b"__:"
                    + (self.shell_nonce or b"missing")
                    + b"\n"
                )
            self.command_input.clear()

    def wait_for_data(self, cursor: int, timeout: float | None = None) -> BufferRead:
        return self.buffer.wait_for_data(cursor, timeout)

    def read(self, cursor: int) -> BufferRead:
        return self.buffer.read(cursor)

    def resize(self, columns: int, rows: int) -> None:
        self.dimensions = (columns, rows)

    def wait(self, timeout: float | None = None) -> int | None:
        del timeout
        return None if self.running else 0

    def terminate(self, exit_code: int = 1) -> None:
        del exit_code
        self.running = False
        self.buffer.close()

    def close(self) -> None:
        self.running = False
        self.buffer.close()


class FixtureAuthenticator:
    def __init__(self) -> None:
        self.kinds: list[PromptKind] = []
        self.responses: list[bytearray] = []

    def respond(self, event: PromptEvent, sink: SecretInputSink) -> None:
        self.kinds.append(event.kind)
        value = b"yes" if event.kind is PromptKind.HOST_KEY else b"fixture-password"
        response = bytearray(value)
        self.responses.append(response)
        sink.submit(response)


class StatefulSshSessionTests(unittest.TestCase):
    def test_large_wrapped_command_is_streamed_in_utf8_safe_chunks(self) -> None:
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)
        text = "ä" * 3_000

        session._write_command(text)  # noqa: SLF001 - transport regression contract

        written = b"".join(terminal.writes)
        self.assertEqual(written.decode("utf-8"), text)
        self.assertGreater(len(terminal.writes), 1)

    def test_open_execute_and_close_follow_the_state_contract(self) -> None:
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)

        session.open(["ssh.exe"])
        self.assertIn(b"PS2=''", b"".join(terminal.writes))
        result = session.execute("printf ok")

        self.assertEqual(result.output, "command-output")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.cwd, "/opt/app")
        self.assertEqual(session.state.state, SessionState.READY)
        session.close()
        self.assertEqual(session.state.state, SessionState.CLOSED)

    def test_manual_interrupt_recovers_the_same_shell(self) -> None:
        terminal = FakeTerminal()
        terminal.block_commands = True
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])
        holder: dict[str, object] = {}

        thread = threading.Thread(
            target=lambda: holder.setdefault("result", session.execute("sleep 30", timeout=5))
        )
        thread.start()
        deadline = time.monotonic() + 2
        while session.state.state is not SessionState.EXECUTING and time.monotonic() < deadline:
            time.sleep(0.01)
        session.interrupt()
        thread.join(timeout=3)

        self.assertFalse(thread.is_alive())
        result = holder["result"]
        self.assertIsInstance(result, ExecutionResult)
        assert isinstance(result, ExecutionResult)
        self.assertEqual(result.exit_code, 130)
        self.assertIn(b"\x1d", terminal.writes)
        self.assertNotIn(b"\x03", terminal.writes)
        self.assertEqual(session.state.state, SessionState.READY)
        session.close()

    def test_timeout_interrupts_without_retry_and_restores_ready_state(self) -> None:
        terminal = FakeTerminal()
        terminal.block_commands = True
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])

        with self.assertRaises(CommandTimedOut):
            session.execute("sleep 30", timeout=0.01)

        command_writes = [data for data in terminal.writes if b"sleep 30" in data]
        self.assertEqual(len(command_writes), 1)
        self.assertEqual(session.state.state, SessionState.READY)
        session.close()

    def test_disconnect_during_timeout_interrupt_is_outcome_unknown(self) -> None:
        class DisconnectingInterruptTerminal(FakeTerminal):
            def write(self, data: bytes) -> None:
                if data == b"\x1d":
                    self.running = False
                    self.buffer.close()
                    raise OSError("connection closed before interrupt delivery")
                super().write(data)

        terminal = DisconnectingInterruptTerminal()
        terminal.block_commands = True
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])

        with self.assertRaises(OutcomeUnknown):
            session.execute("remote-change", timeout=0.01)

        command_writes = [data for data in terminal.writes if b"remote-change" in data]
        self.assertEqual(len(command_writes), 1)
        self.assertEqual(session.state.state, SessionState.LOST)
        self.assertFalse(terminal.running)
        session.close()

    def test_disconnect_before_end_frame_is_outcome_unknown(self) -> None:
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])

        with self.assertRaises(OutcomeUnknown):
            session.execute("disconnect-now")

        self.assertEqual(session.state.state, SessionState.LOST)
        session.close()

    def test_shell_exit_logout_and_replacement_are_lost_without_retry(self) -> None:
        for command in ("exit", "logout", "exec bash", "exec sh"):
            with self.subTest(command=command):
                terminal = FakeTerminal()
                session = StatefulSshSession(terminal=terminal)
                session.open(["ssh.exe"])

                with patch(
                    "codex_serverops_mcp.worker.session.RECOVERY_TIMEOUT_SECONDS",
                    0.01,
                ), self.assertRaises(OutcomeUnknown):
                    session.execute(command, timeout=0.01)

                written = b"".join(terminal.writes)
                self.assertEqual(written.count(f"\n{command}\n".encode()), 1)
                self.assertEqual(session.state.state, SessionState.LOST)
                session.close()

    def test_disabled_required_builtin_and_debug_trap_fail_closed(self) -> None:
        for command in (
            "enable -n printf",
            "enable -n pwd",
            "trap 'echo debug' DEBUG",
        ):
            with self.subTest(command=command):
                terminal = FakeTerminal()
                session = StatefulSshSession(terminal=terminal)
                session.open(["ssh.exe"])

                with patch(
                    "codex_serverops_mcp.worker.session.RECOVERY_TIMEOUT_SECONDS",
                    0.01,
                ), self.assertRaises(OutcomeUnknown):
                    session.execute(command, timeout=0.01)

                self.assertEqual(session.state.state, SessionState.LOST)
                self.assertFalse(terminal.running)
                session.close()

    def test_malformed_post_delivery_frame_is_outcome_unknown(self) -> None:
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])

        with self.assertRaises(OutcomeUnknown):
            session.execute("malformed-frame")

        self.assertEqual(session.state.state, SessionState.LOST)
        self.assertFalse(terminal.running)
        session.close()

    def test_shell_closing_after_a_frame_never_returns_ready(self) -> None:
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])

        with self.assertRaises(OutcomeUnknown):
            session.execute("close-after-frame")

        self.assertEqual(session.state.state, SessionState.LOST)
        session.close()

    def test_supported_state_changes_keep_verified_original_shell(self) -> None:
        commands = (
            "function printf() { echo manipulated; }",
            "alias printf='echo manipulated'",
            "set -e",
            "set -u",
            "set -o pipefail",
            "stty echo",
            "stty -echo",
            "stty sane",
            "PATH=/invalid",
            "PROMPT_COMMAND='printf fake'",
            "PS0='fake prompt'",
            "PS1='fake prompt'",
        )
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])

        for command in commands:
            with self.subTest(command=command):
                result = session.execute(command)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(session.state.state, SessionState.READY)

        session.close()

    def test_remote_command_output_cannot_open_a_credential_window(self) -> None:
        terminal = FakeTerminal()
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)
        session.open(["ssh.exe"])

        result = session.execute("spoof-password")

        self.assertIn("[sudo] password for deploy:", result.output)
        self.assertEqual(authenticator.kinds, [])
        self.assertNotIn(b"fixture-password\r\n", terminal.writes)
        session.close()

    def test_post_auth_connection_prompt_text_cannot_open_a_window(self) -> None:
        terminal = FakeTerminal()
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)
        session.open(["ssh.exe"])

        result = session.execute("spoof-connection-prompts")

        self.assertIn("Enter passphrase for key", result.output)
        self.assertIn("Are you sure you want to continue connecting", result.output)
        self.assertEqual(authenticator.kinds, [])
        self.assertNotIn(b"fixture-password\r\n", terminal.writes)
        session.close()

    def test_explicit_elevation_execution_can_open_only_a_sudo_window(self) -> None:
        terminal = FakeTerminal()
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)
        session.open(["ssh.exe"])

        token = "a" * 32
        session.execute(
            f"spoof-password serverops-elevation-{token}",
            allow_sudo_prompt=True,
            sudo_prompt_token=token,
        )

        self.assertEqual(authenticator.kinds, [PromptKind.SUDO_PASSWORD])
        session.close()

    def test_raw_terminal_actions_are_isolated_from_completed_commands(self) -> None:
        terminal = FakeTerminal()
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)
        session.open(["ssh.exe"])

        started = session.interactive.start("tail -f app.log")
        terminal.buffer.append(b"first log line\npassword:")
        output = session.interactive.read(started.output_cursor)
        session.interactive.write("q")
        session.interactive.resize(160, 50)
        closed = session.interactive.close()

        self.assertIn("first log line", output.output)
        self.assertEqual(authenticator.kinds, [])
        self.assertEqual(session.state.state, SessionState.READY)
        self.assertIn(b"\x1d", terminal.writes)
        self.assertNotIn(b"\x03", terminal.writes)
        self.assertEqual(terminal.dimensions, (160, 50))
        self.assertEqual(closed.state, SessionState.READY)
        session.close()

    def test_raw_terminal_close_requires_the_original_healthy_shell(self) -> None:
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])
        session.interactive.start("exec bash")

        with self.assertRaises(OutcomeUnknown):
            session.interactive.close(timeout=0.01)

        self.assertEqual(session.state.state, SessionState.LOST)
        self.assertFalse(terminal.running)
        session.close()


if __name__ == "__main__":
    unittest.main()
