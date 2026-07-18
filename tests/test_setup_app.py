from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_serverops_mcp.setup.app import run_setup_app
from codex_serverops_mcp.setup.model import SetupAction, SetupRequest, SetupStatus
from codex_serverops_mcp.setup.store import SetupRequestStore


class FakeWindow:
    def run(self):
        return SetupStatus.CREATED, {"profile": {"name": "prod"}}, None


class SetupAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = SetupRequestStore(Path(self.temporary.name) / "runtime")
        self.request = SetupRequest.create(SetupAction.ADD, profile_name="prod")
        self.store.create(self.request)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_window_outcome_is_persisted_without_secret_fields(self) -> None:
        def factory(*_args: object) -> FakeWindow:
            return FakeWindow()

        exit_code = run_setup_app(
            self.request.request_id,
            store=self.store,
            operations=object(),  # type: ignore[arg-type]
            key_generator=object(),  # type: ignore[arg-type]
            window_factory=factory,  # type: ignore[arg-type]
        )

        record = self.store.load(self.request.request_id)
        self.assertEqual(exit_code, 0)
        self.assertEqual(record.status, SetupStatus.CREATED)
        self.assertEqual(record.result, {"profile": {"name": "prod"}})

    def test_window_start_failure_becomes_controlled_terminal_status(self) -> None:
        def factory(*_args: object):
            raise RuntimeError("fixture failure")

        exit_code = run_setup_app(
            self.request.request_id,
            store=self.store,
            operations=object(),  # type: ignore[arg-type]
            key_generator=object(),  # type: ignore[arg-type]
            window_factory=factory,  # type: ignore[arg-type]
        )

        record = self.store.load(self.request.request_id)
        self.assertEqual(exit_code, 3)
        self.assertEqual(record.status, SetupStatus.FAILED)
        self.assertNotIn("fixture failure", record.message or "")


if __name__ == "__main__":
    unittest.main()
