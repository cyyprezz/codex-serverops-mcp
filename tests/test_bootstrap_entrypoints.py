from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "custom-runtime"
            app_data = root / "local-app-data"
            events: list[str] = []
            captured_paths = []
            instance = Mock()
            instance.serve_forever.side_effect = lambda: events.append("serve")
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": str(app_data)}),
                patch.object(
                    sys,
                    "argv",
                    ["serverops-broker", "--runtime", str(runtime)],
                ),
                patch(
                    "codex_serverops_mcp.bootstrap.ensure_local_state",
                    side_effect=lambda paths: (
                        captured_paths.append(paths),
                        events.append("bootstrap"),
                    ),
                ),
                patch.object(
                    broker_server,
                    "BrokerServer",
                    side_effect=lambda _path: events.append("construct") or instance,
                ),
            ):
                broker_server.main()
            self.assertEqual(events, ["bootstrap", "construct", "serve"])
            self.assertEqual(captured_paths[0].runtime_dir, runtime.resolve())
            self.assertEqual(
                captured_paths[0].app_dir,
                app_data / "codex-serverops-mcp",
            )

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
