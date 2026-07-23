from __future__ import annotations

import sys
import unittest
from unittest.mock import Mock, patch

from codex_serverops_mcp import server
from codex_serverops_mcp.broker import server as broker_server
from codex_serverops_mcp.setup import app as setup_app


class BootstrapEntrypointTests(unittest.TestCase):
    def test_mcp_main_bootstraps_before_server_run(self) -> None:
        events: list[str] = []
        mcp = Mock()
        mcp.run.side_effect = lambda **_kwargs: events.append("run")
        with (
            patch.object(
                server,
                "ensure_local_state",
                side_effect=lambda: events.append("bootstrap"),
            ),
            patch.object(server, "build_server", return_value=mcp),
        ):
            server.main()
        self.assertEqual(events, ["bootstrap", "run"])

    def test_broker_main_bootstraps_before_server_construction(self) -> None:
        events: list[str] = []
        instance = Mock()
        instance.serve_forever.side_effect = lambda: events.append("serve")
        with (
            patch.object(sys, "argv", ["serverops-broker"]),
            patch(
                "codex_serverops_mcp.bootstrap.ensure_local_state",
                side_effect=lambda _paths: events.append("bootstrap"),
            ),
            patch.object(
                broker_server,
                "BrokerServer",
                side_effect=lambda _path: events.append("construct") or instance,
            ),
        ):
            broker_server.main()
        self.assertEqual(events, ["bootstrap", "construct", "serve"])

    def test_setup_main_bootstraps_before_assistant(self) -> None:
        events: list[str] = []
        with (
            patch.object(sys, "argv", ["serverops-setup", "--request-id", "setup-123"]),
            patch(
                "codex_serverops_mcp.bootstrap.ensure_local_state",
                side_effect=lambda: events.append("bootstrap"),
            ),
            patch.object(
                setup_app,
                "run_setup_app",
                side_effect=lambda _request_id: events.append("assistant") or 0,
            ),
            self.assertRaises(SystemExit) as exit_context,
        ):
            setup_app.main()
        self.assertEqual(exit_context.exception.code, 0)
        self.assertEqual(events, ["bootstrap", "assistant"])


if __name__ == "__main__":
    unittest.main()
