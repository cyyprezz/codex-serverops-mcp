from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from codex_serverops_mcp.broker.client import BrokerClient
from codex_serverops_mcp.broker.errors import (
    BrokerOutcomeUnknown,
    BrokerUnavailable,
    WorkerOperationError,
)
from codex_serverops_mcp.broker.model import SessionRecord
from codex_serverops_mcp.broker.outcomes import uncertain_outcome_code
from codex_serverops_mcp.broker.supervisor import WorkerHandle, WorkerSupervisor
from codex_serverops_mcp.ipc.errors import IpcClosed
from codex_serverops_mcp.runtime import RuntimeDirectory


class _FailingConnection:
    def __init__(self) -> None:
        self.closed = False

    def send(self, _request) -> None:
        pass

    def receive(self, *, timeout=None):
        del timeout
        raise IpcClosed("fixture disconnect after delivery")

    def close(self) -> None:
        self.closed = True


class _Process:
    def __init__(self) -> None:
        self.terminated = False

    def poll(self):
        return 1 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None) -> int:
        del timeout
        return 1


class BrokerOutcomeTests(unittest.TestCase):
    def test_only_effectful_requests_map_to_specific_unknown_codes(self) -> None:
        self.assertEqual(uncertain_outcome_code("session.exec"), "outcome_unknown")
        self.assertEqual(
            uncertain_outcome_code("worker.file_edit", {"action": "write_text"}),
            "file_outcome_unknown",
        )
        self.assertEqual(
            uncertain_outcome_code("session.elevation", {"action": "exec"}),
            "elevation_outcome_unknown",
        )
        self.assertIsNone(uncertain_outcome_code("session.files", {"action": "read_text"}))
        self.assertIsNone(
            uncertain_outcome_code("session.terminal", {"action": "read"})
        )

    def test_broker_disconnect_after_exec_delivery_is_outcome_unknown(self) -> None:
        client = object.__new__(BrokerClient)
        connection = _FailingConnection()
        client.connection = connection  # type: ignore[assignment]
        client._lock = threading.Lock()  # noqa: SLF001

        with self.assertRaises(BrokerOutcomeUnknown) as captured:
            client.request("session.exec", {"command": "touch /tmp/effect"})

        self.assertEqual(captured.exception.code, "outcome_unknown")
        self.assertTrue(connection.closed)
        self.assertIsNone(client.connection)

    def test_broker_disconnect_after_read_is_unavailable_not_unknown(self) -> None:
        client = object.__new__(BrokerClient)
        connection = _FailingConnection()
        client.connection = connection  # type: ignore[assignment]
        client._lock = threading.Lock()  # noqa: SLF001

        with self.assertRaises(BrokerUnavailable):
            client.request("session.files", {"action": "read_text"})

        self.assertTrue(connection.closed)

    def test_worker_disconnect_invalidates_session_and_preserves_unknown_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            supervisor = WorkerSupervisor(RuntimeDirectory(Path(temporary) / "runtime"))
            session_id = "sess-0123456789abcdef"
            now = time.time()
            record = SessionRecord(
                session_id,
                "prod",
                1234,
                r"\\.\pipe\codex-serverops-worker-test",
                "ready",
                now,
                now,
            )
            connection = _FailingConnection()
            process = _Process()
            handle = WorkerHandle(
                record,
                process,  # type: ignore[arg-type]
                connection,  # type: ignore[arg-type]
                "fixture-token",
                threading.Lock(),
            )
            supervisor._handles[session_id] = handle  # noqa: SLF001
            supervisor.registry.add(record)

            with self.assertRaises(WorkerOperationError) as captured:
                supervisor.request(
                    session_id,
                    "worker.file_edit",
                    {"action": "write_text"},
                    timeout=1,
                )

            self.assertEqual(captured.exception.code, "file_outcome_unknown")
            self.assertEqual(supervisor.registry.get(session_id).state, "lost")
            self.assertNotIn(session_id, supervisor._handles)  # noqa: SLF001
            self.assertTrue(connection.closed)
            self.assertTrue(process.terminated)
            self.assertEqual(supervisor.shutdown(session_id).state, "lost")
            self.assertEqual(supervisor.registry.list(), ())


if __name__ == "__main__":
    unittest.main()
