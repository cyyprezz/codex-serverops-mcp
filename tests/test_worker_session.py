from __future__ import annotations

import re
import threading
import time
import unittest
from collections.abc import Sequence
from pathlib import Path

from codex_serverops_mcp.auth.errors import AuthenticationCancelled
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind
from codex_serverops_mcp.terminal.buffer import BufferRead, TerminalRingBuffer
from codex_serverops_mcp.worker.authentication import SecretInputSink
from codex_serverops_mcp.worker.errors import CommandTimedOut, OutcomeUnknown
from codex_serverops_mcp.worker.result import ExecutionResult
from codex_serverops_mcp.worker.session import StatefulSshSession
from codex_serverops_mcp.worker.state import SessionState

TOKEN = re.compile(rb"__SERVEROPS_BEGIN_([A-F0-9]+)__")
END_TOKEN = re.compile(rb"__SERVEROPS_END_([A-F0-9]+)__:130")


class FakeTerminal:
    backend_name = "conpty"

    def __init__(self, *, auth_prompts: bool = False) -> None:
        self.buffer = TerminalRingBuffer(1_048_576)
        self.running = False
        self.auth_prompts = auth_prompts
        self.writes: list[bytes] = []
        self.block_commands = False
        self.dimensions = (120, 30)

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
        if self.auth_prompts:
            self.buffer.append(b"Are you sure you want to continue connecting (yes/no)?")
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
        match = TOKEN.search(data)
        if match:
            token = match.group(1)
            self.buffer.append(b"\n__SERVEROPS_BEGIN_" + token + b"__\n")
            if b"disconnect-now" in data:
                self.running = False
                self.buffer.close()
            elif not self.block_commands:
                output = (
                    b"[sudo] password for deploy:\n"
                    if b"spoof-password" in data
                    else b"command-output\n"
                )
                self.buffer.append(
                    output
                    + b"__SERVEROPS_END_"
                    + token
                    + b"__:0\n__SERVEROPS_CWD_"
                    + token
                    + b"__:/opt/app\n"
                )
            return
        recovery = END_TOKEN.search(data)
        if recovery:
            token = recovery.group(1)
            self.buffer.append(
                b"\n__SERVEROPS_END_"
                + token
                + b"__:130\n__SERVEROPS_CWD_"
                + token
                + b"__:/opt/app\n"
            )
        if data == b"exit\r\n":
            self.running = False
            self.buffer.close()

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


class CancellingAuthenticator:
    def respond(self, event: PromptEvent, sink: SecretInputSink) -> None:
        del event, sink
        raise AuthenticationCancelled("cancelled by test operator")


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

    def test_authentication_capability_stays_worker_local_and_zeroes_responses(self) -> None:
        terminal = FakeTerminal(auth_prompts=True)
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)

        session.open(["ssh.exe"])

        self.assertEqual(authenticator.kinds, [PromptKind.HOST_KEY, PromptKind.PASSWORD])
        self.assertTrue(all(not any(response) for response in authenticator.responses))
        self.assertEqual(session.state.state, SessionState.READY)
        session.close()

    def test_authentication_cancellation_terminates_the_ambiguous_ssh_process(self) -> None:
        terminal = FakeTerminal(auth_prompts=True)
        session = StatefulSshSession(
            terminal=terminal,
            authenticator=CancellingAuthenticator(),
        )

        with self.assertRaises(AuthenticationCancelled):
            session.open(["ssh.exe"])

        self.assertFalse(terminal.running)
        self.assertEqual(session.state.state, SessionState.FAILED)

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

    def test_disconnect_before_end_frame_is_outcome_unknown(self) -> None:
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])

        with self.assertRaises(OutcomeUnknown):
            session.execute("disconnect-now")

        self.assertEqual(session.state.state, SessionState.LOST)
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

    def test_explicit_elevation_execution_can_open_only_a_sudo_window(self) -> None:
        terminal = FakeTerminal()
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)
        session.open(["ssh.exe"])

        session.execute("spoof-password", allow_sudo_prompt=True)

        self.assertEqual(authenticator.kinds, [PromptKind.SUDO_PASSWORD])
        session.close()

    def test_raw_terminal_actions_are_isolated_from_completed_commands(self) -> None:
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)
        session.open(["ssh.exe"])

        started = session.interactive.start("tail -f app.log")
        terminal.buffer.append(b"first log line\npassword:")
        output = session.interactive.read(started.output_cursor)
        session.interactive.write("q")
        session.interactive.resize(160, 50)
        closed = session.interactive.close()

        self.assertIn("first log line", output.output)
        self.assertEqual(session.state.state, SessionState.READY)
        self.assertIn(b"\x1d", terminal.writes)
        self.assertNotIn(b"\x03", terminal.writes)
        self.assertEqual(terminal.dimensions, (160, 50))
        self.assertEqual(closed.state, SessionState.READY)
        session.close()


if __name__ == "__main__":
    unittest.main()
