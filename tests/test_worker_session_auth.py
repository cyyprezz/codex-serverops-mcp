from __future__ import annotations

import time
import unittest

from codex_serverops_mcp.auth.errors import AuthenticationCancelled
from codex_serverops_mcp.ssh.prompts import PromptKind
from codex_serverops_mcp.worker.session import StatefulSshSession
from codex_serverops_mcp.worker.state import SessionState

if __package__:
    from .test_worker_session import TOKEN, FakeTerminal, FixtureAuthenticator
else:
    from test_worker_session import TOKEN, FakeTerminal, FixtureAuthenticator


class DeferredSudoTerminal(FakeTerminal):
    def write(self, data: bytes) -> None:
        super().write(data)
        if b"delayed-sudo" in data:
            self.buffer.append(
                b"[sudo] password for deploy: serverops-elevation-" + b"a" * 32 + b"\n"
            )


class SlowCompletingAuthenticator(FixtureAuthenticator):
    def __init__(self, terminal: DeferredSudoTerminal) -> None:
        super().__init__()
        self.terminal = terminal

    def respond(self, event, sink) -> None:
        time.sleep(0.2)
        super().respond(event, sink)
        token = TOKEN.findall(b"".join(self.terminal.writes))[-1]
        nonce = self.terminal.shell_nonce or b"missing"
        self.terminal.buffer.append(
            b"\n__SERVEROPS_DEBUG_"
            + token
            + b"__\n__SERVEROPS_DEBUG_END_"
            + token
            + b"__\n__SERVEROPS_END_"
            + token
            + b"__:0\n__SERVEROPS_CWD_"
            + token
            + b"__:/opt/app\n__SERVEROPS_HEALTH_"
            + token
            + b"__:"
            + nonce
            + b"\n"
        )


class StatefulSshSessionAuthenticationTests(unittest.TestCase):
    def test_local_sudo_authentication_does_not_consume_remote_command_timeout(self) -> None:
        terminal = DeferredSudoTerminal()
        authenticator = SlowCompletingAuthenticator(terminal)
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)
        session.open(["ssh.exe"])
        terminal.block_commands = True

        result = session.execute(
            "delayed-sudo",
            timeout=0.1,
            allow_sudo_prompt=True,
            sudo_prompt_token="a" * 32,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(authenticator.kinds, [PromptKind.SUDO_PASSWORD])
        self.assertEqual(session.state.state, SessionState.READY)
        session.close()

    def test_elevation_prompt_fails_closed_without_exact_token_binding(self) -> None:
        session = StatefulSshSession(terminal=FakeTerminal())
        session.open(["ssh.exe"])
        for allow_sudo, token in ((True, None), (False, "unexpected-token")):
            with self.subTest(allow_sudo=allow_sudo, token=token), self.assertRaisesRegex(
                ValueError,
                "operation-bound prompt token",
            ):
                session.execute(
                    "true",
                    allow_sudo_prompt=allow_sudo,
                    sudo_prompt_token=token,
                )
        session.close()

    def test_elevation_ignores_a_sudo_prompt_with_the_wrong_token(self) -> None:
        terminal = FakeTerminal()
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)
        session.open(["ssh.exe"])

        session.execute(
            "spoof-password serverops-elevation-wrongtoken",
            allow_sudo_prompt=True,
            sudo_prompt_token="a" * 32,
        )

        self.assertEqual(authenticator.kinds, [])
        session.close()

    def test_startup_sudo_prompt_fails_closed_without_exact_token_binding(self) -> None:
        for allow_sudo, token in ((True, None), (False, "unexpected-token")):
            with self.subTest(allow_sudo=allow_sudo, token=token):
                session = StatefulSshSession(terminal=FakeTerminal())
                with self.assertRaisesRegex(ValueError, "operation-bound prompt token"):
                    session.open(
                        ["ssh.exe"],
                        allow_sudo_prompt=allow_sudo,
                        sudo_prompt_token=token,
                    )
                self.assertEqual(session.state.state, SessionState.CREATED)

    def test_connection_prompt_text_is_never_authenticated_from_terminal_output(self) -> None:
        terminal = FakeTerminal(auth_prompts=True)
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)

        session.open(["ssh.exe"])

        self.assertEqual(authenticator.kinds, [])
        self.assertNotIn(b"fixture-password\r\n", terminal.writes)
        self.assertEqual(session.state.state, SessionState.READY)
        session.close()

    def test_root_startup_ignores_sudo_banner_without_operation_token(self) -> None:
        terminal = FakeTerminal(startup_sudo_prompt="[sudo] password for deploy: fake-banner")
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)

        session.open(
            ["ssh.exe"],
            allow_sudo_prompt=True,
            sudo_prompt_token="expected-operation-token",
        )

        self.assertEqual(authenticator.kinds, [])
        self.assertNotIn(b"fixture-password\r\n", terminal.writes)
        self.assertEqual(session.state.state, SessionState.READY)
        session.close()

    def test_root_startup_accepts_only_its_operation_bound_sudo_prompt(self) -> None:
        token = "expected-operation-token"
        terminal = FakeTerminal(
            startup_sudo_prompt=f"[sudo] password for deploy: serverops-root-{token}"
        )
        authenticator = FixtureAuthenticator()
        session = StatefulSshSession(terminal=terminal, authenticator=authenticator)

        session.open(
            ["ssh.exe"],
            allow_sudo_prompt=True,
            sudo_prompt_token=token,
        )

        self.assertEqual(authenticator.kinds, [PromptKind.SUDO_PASSWORD])
        self.assertIn(b"fixture-password\r\n", terminal.writes)
        self.assertEqual(session.state.state, SessionState.READY)
        session.close()

    def test_authentication_cancellation_terminates_the_ambiguous_ssh_process(self) -> None:
        terminal = FakeTerminal()
        session = StatefulSshSession(terminal=terminal)

        def cancelled() -> None:
            raise AuthenticationCancelled("cancelled by test operator")

        with self.assertRaises(AuthenticationCancelled):
            session.open(["ssh.exe"], failure_check=cancelled)

        self.assertFalse(terminal.running)
        self.assertEqual(session.state.state, SessionState.FAILED)


if __name__ == "__main__":
    unittest.main()
