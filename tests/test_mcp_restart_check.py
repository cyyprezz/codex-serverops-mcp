from __future__ import annotations

import unittest

from scripts.mcp_restart_rediscovery_check import command_completed_once, verify_restart_state


class McpRestartCheckTests(unittest.TestCase):
    def test_command_marker_allows_only_surrounding_terminal_whitespace(self) -> None:
        result = {
            "status": "completed",
            "exit_code": 0,
            "output": "before-mcp-restart\n\n\n",
        }

        self.assertTrue(command_completed_once(result, "before-mcp-restart"))
        for output in (
            "before-mcp-restart\nunexpected",
            "before-mcp-restart\nbefore-mcp-restart",
        ):
            with self.subTest(output=output):
                self.assertFalse(
                    command_completed_once(
                        {**result, "output": output},
                        "before-mcp-restart",
                    )
                )
        self.assertFalse(command_completed_once({**result, "exit_code": 1}, "before-mcp-restart"))

    def test_restart_state_requires_rediscovery_state_and_no_retry(self) -> None:
        verify_restart_state(
            "sess-0123456789abcdef",
            {"sessions": [{"session_id": "sess-0123456789abcdef"}]},
            {"session_id": "sess-0123456789abcdef", "state": "ready"},
            {"output": "/opt/test\n"},
            {"rediscovered": True, "command_retried": False},
            "/opt/test",
        )

    def test_restart_state_rejects_any_retry_claim(self) -> None:
        with self.assertRaisesRegex(AssertionError, "no-retry"):
            verify_restart_state(
                "sess-0123456789abcdef",
                {"sessions": [{"session_id": "sess-0123456789abcdef"}]},
                {"session_id": "sess-0123456789abcdef", "state": "ready"},
                {"output": "/opt/test\n"},
                {"rediscovered": True, "command_retried": True},
                "/opt/test",
            )


if __name__ == "__main__":
    unittest.main()
