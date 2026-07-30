from __future__ import annotations

import unittest

import codex_serverops_mcp


class VersionContractTests(unittest.TestCase):
    def test_spike_versions_are_explicit_positive_integers(self) -> None:
        self.assertEqual(codex_serverops_mcp.PACKAGE_VERSION, "0.1.1")
        expected = {
            "broker": (codex_serverops_mcp.BROKER_PROTOCOL_VERSION, 3),
            "worker": (codex_serverops_mcp.WORKER_PROTOCOL_VERSION, 3),
            "config": (codex_serverops_mcp.CONFIG_SCHEMA_VERSION, 1),
        }
        for value, exact in expected.values():
            self.assertIsInstance(value, int)
            self.assertGreater(value, 0)
            self.assertEqual(value, exact)


if __name__ == "__main__":
    unittest.main()
