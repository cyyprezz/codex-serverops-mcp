from __future__ import annotations

import unittest

from codex_serverops_mcp.worker.errors import InvalidSessionState
from codex_serverops_mcp.worker.state import SessionState, SessionStateMachine


class SessionStateMachineTests(unittest.TestCase):
    def test_authentication_returns_to_the_exact_prior_state(self) -> None:
        machine = SessionStateMachine()
        machine.transition(SessionState.STARTING)
        machine.transition(SessionState.READY)
        machine.transition(SessionState.EXECUTING)

        machine.begin_authentication()
        self.assertEqual(machine.state, SessionState.AUTHENTICATION_REQUIRED)
        machine.finish_authentication()

        self.assertEqual(machine.state, SessionState.EXECUTING)

    def test_invalid_transition_fails_closed(self) -> None:
        machine = SessionStateMachine()
        with self.assertRaises(InvalidSessionState):
            machine.transition(SessionState.READY)

    def test_close_is_idempotent_at_the_boundary(self) -> None:
        machine = SessionStateMachine()
        self.assertTrue(machine.begin_close())
        machine.transition(SessionState.CLOSED)
        self.assertFalse(machine.begin_close())


if __name__ == "__main__":
    unittest.main()
