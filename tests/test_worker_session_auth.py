from __future__ import annotations

import unittest

from codex_serverops_mcp.auth.errors import AuthenticationCancelled
from codex_serverops_mcp.ssh.prompts import PromptKind
from codex_serverops_mcp.worker.session import StatefulSshSession
from codex_serverops_mcp.worker.state import SessionState

if __package__:
    from .test_worker_session import FakeTerminal, FixtureAuthenticator
else:
    from test_worker_session import FakeTerminal, FixtureAuthenticator


class StatefulSshSessionAuthenticationTests(unittest.TestCase):
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
