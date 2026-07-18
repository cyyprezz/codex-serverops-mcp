from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt", "broker manager starts a Windows named-pipe broker")
class BrokerManagerTests(unittest.TestCase):
    def test_status_sharing_violation_is_a_controlled_unavailable_result(self) -> None:
        from codex_serverops_mcp.broker.client import BrokerClient
        from codex_serverops_mcp.broker.errors import BrokerUnavailable

        with (
            patch(
                "codex_serverops_mcp.broker.client.RuntimeDirectory.read_json",
                side_effect=PermissionError("transient Windows sharing violation"),
            ),
            self.assertRaisesRegex(BrokerUnavailable, "status is unavailable"),
        ):
            BrokerClient()

    def test_manager_starts_broker_and_later_clients_rediscover_it(self) -> None:
        from codex_serverops_mcp.broker.manager import BrokerManager

        with tempfile.TemporaryDirectory() as temporary:
            manager = BrokerManager(Path(temporary) / "runtime")
            try:
                with manager.connect() as first:
                    first_pid = first.request("broker.ping")["pid"]
                with manager.connect() as second:
                    self.assertEqual(second.request("broker.ping")["pid"], first_pid)
                    second.request("broker.shutdown")
                manager.wait_for_launched_broker()
            finally:
                process = manager._launched_process
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
