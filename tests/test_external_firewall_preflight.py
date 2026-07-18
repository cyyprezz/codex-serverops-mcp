from __future__ import annotations

import unittest

from scripts.external_firewall_preflight import parse_tool_paths


class ExternalFirewallPreflightTests(unittest.TestCase):
    def test_exact_tool_rows_parse_without_claiming_missing_tools(self) -> None:
        self.assertEqual(
            parse_tool_paths(
                "ufw=/usr/sbin/ufw\n"
                "iptables=/usr/sbin/iptables\n"
                "nft=\n"
                "systemd-run=/usr/bin/systemd-run\n"
            ),
            {
                "ufw": "/usr/sbin/ufw",
                "iptables": "/usr/sbin/iptables",
                "nft": None,
                "systemd-run": "/usr/bin/systemd-run",
            },
        )

    def test_duplicate_or_relative_tool_rows_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid tool row"):
            parse_tool_paths("ufw=/usr/sbin/ufw\nufw=/other\n")
        with self.assertRaisesRegex(ValueError, "non-absolute"):
            parse_tool_paths(
                "ufw=relative\niptables=\nnft=\nsystemd-run=/usr/bin/systemd-run\n"
            )


if __name__ == "__main__":
    unittest.main()
