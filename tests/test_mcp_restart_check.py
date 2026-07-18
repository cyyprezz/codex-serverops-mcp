from __future__ import annotations

import unittest

from scripts.mcp_restart_rediscovery_check import verify_restart_state


class McpRestartCheckTests(unittest.TestCase):
    def test_restart_state_requires_rediscovery_state_and_no_retry(self) -> None:
        verify_restart_state(
            "sess-0123456789abcdef",
            {"sessions": [{"session_id": "sess-0123456789abcdef"}]},
            {"session_id": "sess-0123456789abcdef", "state": "ready"},
            {"output": "/opt/test\n"},
            {"reconnected": True, "command_retried": False},
            "/opt/test",
        )

    def test_restart_state_rejects_any_retry_claim(self) -> None:
        with self.assertRaisesRegex(AssertionError, "no-retry"):
            verify_restart_state(
                "sess-0123456789abcdef",
                {"sessions": [{"session_id": "sess-0123456789abcdef"}]},
                {"session_id": "sess-0123456789abcdef", "state": "ready"},
                {"output": "/opt/test\n"},
                {"reconnected": True, "command_retried": True},
                "/opt/test",
            )


if __name__ == "__main__":
    unittest.main()
