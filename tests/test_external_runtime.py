from __future__ import annotations

import unittest
from pathlib import Path

from codex_serverops_mcp.broker.manager import BrokerManager
from scripts._external_runtime import isolated_external_services


class ExternalRuntimeTests(unittest.TestCase):
    def test_external_services_use_an_isolated_non_scheduled_broker_runtime(self) -> None:
        with isolated_external_services() as services:
            manager = services.broker
            self.assertIsInstance(manager, BrokerManager)
            runtime_path = manager.runtime_path
            self.assertIsNotNone(runtime_path)
            assert runtime_path is not None
            self.assertEqual(Path(runtime_path).name, "runtime")
            temporary_root = Path(runtime_path).parent
            self.assertTrue(temporary_root.exists())

        self.assertFalse(temporary_root.exists())


if __name__ == "__main__":
    unittest.main()
