from __future__ import annotations

import unittest
from unittest.mock import patch

from codex_serverops_mcp.broker.errors import BrokerRemoteError
from scripts.external_interrupt_disconnect_check import (
    NETWORK_COMMAND,
    SCHEDULER_COMMAND_TIMEOUT_SECONDS,
    _output_matches_marker,
    _trigger_connection_reset,
    _verify_firewall_cleanup,
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
    def test_firewall_cleanup_poll_tolerates_delayed_systemd_collection(self) -> None:
        class Services:
            def __init__(self) -> None:
                self.outputs = iter(("unit still collecting", "\n"))
                self.closed = False

            def server_connection(self, action: str, **_parameters: str) -> dict[str, object]:
                if action == "open":
                    return {"session_id": "sess-0123456789abcdef"}
                if action == "close":
                    self.closed = True
                    return {"status": "closed"}
                raise AssertionError(f"unexpected connection action: {action}")

            def server_exec(self, _session_id: str, _command: str) -> dict[str, object]:
                return {"exit_code": 0, "output": next(self.outputs)}

        services = Services()
        with patch(
            "scripts.external_interrupt_disconnect_check.time.sleep"
        ) as sleep:
            _verify_firewall_cleanup(
                services,  # type: ignore[arg-type]
                "fixture-test",
                "serverops-cut-012345abcdef",
            )

        sleep.assert_called_once_with(1)
        self.assertTrue(services.closed)

    def test_firewall_cleanup_poll_remains_bounded_and_reports_residue(self) -> None:
        class Services:
            def __init__(self) -> None:
                self.closed = False

            def server_connection(self, action: str, **_parameters: str) -> dict[str, object]:
                if action == "open":
                    return {"session_id": "sess-0123456789abcdef"}
                if action == "close":
                    self.closed = True
                    return {"status": "closed"}
                raise AssertionError(f"unexpected connection action: {action}")

            def server_exec(self, _session_id: str, _command: str) -> dict[str, object]:
                return {"exit_code": 0, "output": "unit still collecting"}

        services = Services()
        with (
            patch(
                "scripts.external_interrupt_disconnect_check.time.monotonic",
                side_effect=(0, 35),
            ),
            self.assertRaisesRegex(AssertionError, "unit still collecting"),
        ):
            _verify_firewall_cleanup(
                services,  # type: ignore[arg-type]
                "fixture-test",
                "serverops-cut-012345abcdef",
            )

        self.assertTrue(services.closed)

    def test_disconnect_may_happen_during_scheduler_or_network_probe(self) -> None:
        class Services:
            def __init__(self, disconnect_call: int) -> None:
                self.disconnect_call = disconnect_call
                self.calls: list[tuple[str, float | None]] = []

            def server_exec(
                self,
                _session_id: str,
                command: str,
                timeout: float | None = None,
            ) -> dict[str, object]:
                self.calls.append((command, timeout))
                if len(self.calls) == self.disconnect_call:
                    raise BrokerRemoteError("outcome_unknown", "connection reset")
                return {"status": "completed", "exit_code": 0, "output": "scheduled\n"}

        scheduler = Services(1)
        self.assertEqual(
            _trigger_connection_reset(scheduler, "session-1", "schedule"),  # type: ignore[arg-type]
            "scheduler_command",
        )
        self.assertEqual(
            scheduler.calls,
            [("schedule", SCHEDULER_COMMAND_TIMEOUT_SECONDS)],
        )

        probe = Services(2)
        self.assertEqual(
            _trigger_connection_reset(probe, "session-1", "schedule"),  # type: ignore[arg-type]
            "network_probe",
        )
        self.assertEqual(
            probe.calls,
            [
                ("schedule", SCHEDULER_COMMAND_TIMEOUT_SECONDS),
                (NETWORK_COMMAND, 30),
            ],
        )

    def test_interrupt_recovery_marker_allows_only_surrounding_whitespace(self) -> None:
        self.assertTrue(
            _output_matches_marker(
                {"exit_code": 0, "output": "\r\nserverops-after-interrupt\n\n"},
                "serverops-after-interrupt",
            )
        )
        self.assertFalse(
            _output_matches_marker(
                {"exit_code": 0, "output": "serverops-after-interrupt\nunexpected"},
                "serverops-after-interrupt",
            )
        )

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
        self.assertIn("--no-block", command)
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
