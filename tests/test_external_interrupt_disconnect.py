from __future__ import annotations

import unittest

from scripts.external_interrupt_disconnect_check import (
    build_firewall_schedule_command,
    diagnose_unit,
    ensure_elevation,
)


class FakeElevationServices:
    def __init__(self, *, active: bool) -> None:
        self.active = active
        self.actions: list[str] = []

    def server_elevation(
        self,
        action: str,
        _session_id: str,
    ) -> dict[str, object]:
        self.actions.append(action)
        if action == "status":
            return {"status": "active" if self.active else "inactive", "active": self.active}
        if action == "acquire":
            self.active = True
            return {"status": "acquired", "active": True}
        raise AssertionError(f"unexpected action: {action}")


class ExternalInterruptDisconnectTests(unittest.TestCase):
    def test_elevation_reuses_an_active_sudo_timestamp(self) -> None:
        services = FakeElevationServices(active=True)

        result = ensure_elevation(services, "session-1")  # type: ignore[arg-type]

        self.assertTrue(result["active"])
        self.assertEqual(services.actions, ["status"])

    def test_elevation_prompts_only_when_the_timestamp_is_inactive(self) -> None:
        services = FakeElevationServices(active=False)

        result = ensure_elevation(services, "session-1")  # type: ignore[arg-type]

        self.assertTrue(result["active"])
        self.assertEqual(services.actions, ["status", "acquire"])

    def test_firewall_command_is_connection_specific_and_self_reverting(self) -> None:
        command = build_firewall_schedule_command("012345abcdef")

        self.assertIn("set -- $SSH_CONNECTION", command)
        self.assertIn("iptables -I INPUT", command)
        self.assertIn('-s "$1" --sport "$2" -d "$3" --dport "$4"', command)
        self.assertIn("--on-active=5s", command)
        self.assertIn("RuntimeMaxSec=25s", command)
        self.assertIn("trap cleanup EXIT TERM INT", command)
        self.assertLess(command.index("trap cleanup"), command.index("iptables -I"))
        self.assertNotIn("${rule[@]}", command)
        self.assertNotIn("ufw allow", command)
        self.assertNotIn("ufw delete", command)

    def test_firewall_command_rejects_unbounded_unit_names(self) -> None:
        for token in ("short", "ABCDEF012345", "0123456789abcdef"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                build_firewall_schedule_command(token)

    def test_unit_diagnosis_rejects_unmarked_names_before_connection(self) -> None:
        for unit in ("ssh", "serverops-cut-short", "serverops-cut-ABCDEF012345"):
            with self.subTest(unit=unit), self.assertRaises(ValueError):
                diagnose_unit("fixture-test", unit)


if __name__ == "__main__":
    unittest.main()
