from __future__ import annotations

import unittest
from collections.abc import Mapping

from codex_serverops_mcp.worker.protocol import WorkerProtocolHandler


class FakeSessionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.state = "created"

    def open(self) -> dict[str, object]:
        self.calls.append(("open", None))
        self.state = "ready"
        return self.status()

    def execute(self, command: str, timeout: float | None = None) -> dict[str, object]:
        self.calls.append(("exec", (command, timeout)))
        return {"status": "completed", "exit_code": 0, "output": "ok"}

    def terminal(self, action: str, payload: Mapping[str, object]) -> dict[str, object]:
        self.calls.append(("terminal", (action, dict(payload))))
        return {"status": "running", "state": "interactive"}

    def files(
        self,
        action: str,
        payload: Mapping[str, object],
        *,
        write: bool,
    ) -> dict[str, object]:
        self.calls.append(("file_edit" if write else "files", (action, dict(payload))))
        return {"status": "updated" if write else "completed"}

    def elevation(
        self,
        action: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self.calls.append(("elevation", (action, dict(payload))))
        return {"status": "completed", "elevated": action == "exec"}

    def status(self) -> dict[str, object]:
        return {"state": self.state, "cwd": None}

    def close(self) -> None:
        self.calls.append(("close", None))
        self.state = "closed"


class WorkerProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FakeSessionService()
        self.handler = WorkerProtocolHandler(
            "sess-0123456789abcdef",
            "prod",
            service=self.service,
        )

    def test_open_exec_terminal_and_shutdown_are_explicit_operations(self) -> None:
        opened = self.handler.handle("worker.open", {})
        executed = self.handler.handle(
            "worker.exec",
            {"command": "pwd", "timeout": 12.5},
        )
        terminal = self.handler.handle(
            "worker.terminal",
            {"action": "read", "cursor": 0, "timeout": 1},
        )
        stopped = self.handler.handle("worker.shutdown", {})

        self.assertEqual(opened.payload["session_id"], "sess-0123456789abcdef")
        self.assertEqual(opened.payload["state"], "ready")
        self.assertEqual(executed.payload["exit_code"], 0)
        self.assertEqual(terminal.payload["state"], "interactive")
        self.assertTrue(stopped.stop)
        self.assertEqual(
            self.service.calls,
            [
                ("open", None),
                ("exec", ("pwd", 12.5)),
                ("terminal", ("read", {"cursor": 0, "timeout": 1})),
                ("close", None),
            ],
        )

    def test_unknown_or_extra_fields_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            self.handler.handle("worker.exec", {"command": "pwd", "unexpected": True})
        with self.assertRaises(ValueError):
            self.handler.handle("worker.terminal", {"action": "resize", "columns": 80})
        with self.assertRaises(ValueError):
            self.handler.handle("worker.unknown", {})

    def test_file_operations_have_exact_action_specific_fields(self) -> None:
        read = self.handler.handle(
            "worker.files",
            {"action": "read_text", "path": "/opt/app/a", "byte_limit": 100},
        )
        edit = self.handler.handle(
            "worker.file_edit",
            {
                "action": "rename",
                "path": "/opt/app/a",
                "destination_path": "/opt/app/b",
            },
        )

        self.assertEqual(read.payload["status"], "completed")
        self.assertEqual(edit.payload["status"], "updated")
        with self.assertRaises(ValueError):
            self.handler.handle(
                "worker.files",
                {"action": "stat", "path": "/opt/app", "content": "unexpected"},
            )
        with self.assertRaises(ValueError):
            self.handler.handle(
                "worker.file_edit",
                {"action": "write_text", "path": "/opt/app/a"},
            )

    def test_elevation_operations_have_exact_action_specific_fields(self) -> None:
        acquired = self.handler.handle("worker.elevation", {"action": "acquire"})
        executed = self.handler.handle(
            "worker.elevation",
            {"action": "exec", "command": "id -u", "timeout": 5},
        )

        self.assertEqual(acquired.payload["status"], "completed")
        self.assertTrue(executed.payload["elevated"])
        with self.assertRaises(ValueError):
            self.handler.handle(
                "worker.elevation",
                {"action": "status", "command": "unexpected"},
            )
        with self.assertRaises(ValueError):
            self.handler.handle("worker.elevation", {"action": "open_root_session"})


if __name__ == "__main__":
    unittest.main()
