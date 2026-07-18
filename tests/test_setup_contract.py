from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_serverops_mcp.setup.launcher import VisibleSetupProcessLauncher
from codex_serverops_mcp.setup.model import (
    SetupAction,
    SetupRequest,
    SetupStatus,
    ensure_non_secret_result,
)
from codex_serverops_mcp.setup.service import SetupCoordinator
from codex_serverops_mcp.setup.store import SetupRequestStore


class FakeProcess:
    pid = 1234


class FakeLauncher:
    def __init__(self) -> None:
        self.request_ids: list[str] = []

    def launch(self, request_id: str) -> FakeProcess:
        self.request_ids.append(request_id)
        return FakeProcess()


class SetupContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = SetupRequestStore(Path(self.temporary.name) / "runtime")
        self.launcher = FakeLauncher()
        self.coordinator = SetupCoordinator(self.store, self.launcher)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_add_request_returns_only_non_secret_polling_contract(self) -> None:
        result = self.coordinator.start(
            "add",
            profile_name="new-prod",
            suggested_host="192.0.2.44",
            suggested_user="deploy",
        )

        self.assertEqual(result["status"], "user_interaction_required")
        self.assertEqual(result["action"], "add")
        self.assertEqual(self.launcher.request_ids, [result["request_id"]])
        self.assertNotIn("host", result)
        self.assertNotIn("user", result)

    def test_non_add_actions_require_profile_and_reject_suggestions(self) -> None:
        with self.assertRaises(ValueError):
            self.coordinator.start("edit")
        with self.assertRaises(ValueError):
            self.coordinator.start("test", profile_name="prod", suggested_host="host")
        self.assertEqual(self.launcher.request_ids, [])

    def test_wait_observes_terminal_update_without_unbounded_blocking(self) -> None:
        started = self.coordinator.start("test", profile_name="prod")
        request_id = str(started["request_id"])

        def complete() -> None:
            time.sleep(0.05)
            self.store.update(
                request_id,
                SetupStatus.TESTED,
                result={"profile": "prod", "connection": "ready"},
            )

        worker = threading.Thread(target=complete)
        worker.start()
        result = self.coordinator.wait(request_id, 1)
        worker.join()

        self.assertEqual(result["status"], "tested")
        self.assertEqual(result["connection"], "ready")

    def test_expired_and_completed_requests_cannot_be_rewritten(self) -> None:
        request = SetupRequest.create(SetupAction.ADD, now=100)
        self.store.create(request)
        expired = self.store.expire_if_needed(request.request_id, now=request.expires_at)

        self.assertEqual(expired.status, SetupStatus.EXPIRED)
        with self.assertRaises(ValueError):
            self.store.update(request.request_id, SetupStatus.CREATED)

    def test_setup_results_reject_secret_fields_recursively(self) -> None:
        for forbidden in (
            {"password": "secret"},
            {"nested": {"key_passphrase": "secret"}},
            {"private_key_content": "secret"},
        ):
            with self.assertRaises(ValueError):
                ensure_non_secret_result(forbidden)
        ensure_non_secret_result({"authentication": "interactive_password"})

    def test_visible_launcher_passes_only_request_id_on_command_line(self) -> None:
        launcher = VisibleSetupProcessLauncher()
        with (
            patch.object(launcher, "_windowed_python", return_value=Path("pythonw.exe")),
            patch("codex_serverops_mcp.setup.launcher.subprocess.Popen") as popen,
        ):
            popen.return_value = FakeProcess()
            launcher.launch("setup-0123456789abcdef01234567")

        arguments = popen.call_args.args[0]
        self.assertEqual(
            arguments,
            [
                "pythonw.exe",
                "-m",
                "codex_serverops_mcp.setup.app",
                "--request-id",
                "setup-0123456789abcdef01234567",
            ],
        )
        self.assertNotIn("password", repr(popen.call_args).lower())


if __name__ == "__main__":
    unittest.main()
