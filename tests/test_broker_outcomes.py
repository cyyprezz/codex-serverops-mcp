from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_serverops_mcp import BROKER_PROTOCOL_VERSION
from codex_serverops_mcp.broker.client import BrokerClient
from codex_serverops_mcp.broker.errors import (
    BrokerOutcomeUnknown,
    BrokerUnavailable,
    WorkerOperationError,
)
from codex_serverops_mcp.broker.model import SessionRecord
from codex_serverops_mcp.broker.outcomes import uncertain_outcome_code
from codex_serverops_mcp.broker.server import BrokerServer
from codex_serverops_mcp.broker.supervisor import WorkerHandle, WorkerSupervisor
from codex_serverops_mcp.broker.timeouts import (
    DEFAULT_BROKER_RESPONSE_TIMEOUT_SECONDS,
    LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS,
    WORKER_LONG_OPERATION_TIMEOUT_SECONDS,
    broker_response_timeout,
)
from codex_serverops_mcp.ipc.errors import IpcClosed
from codex_serverops_mcp.runtime import RuntimeDirectory


class _FailingConnection:
    def __init__(self) -> None:
        self.closed = False
        self.receive_timeout = None

    def send(self, _request) -> None:
        pass

    def receive(self, *, timeout=None):
        self.receive_timeout = timeout
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
    def test_rediscover_returns_preserved_lost_metadata_without_worker_request(self) -> None:
        session_id = "sess-0123456789abcdef"
        record = SessionRecord(
            session_id,
            "prod",
            1234,
            r"\\.\pipe\codex-serverops-worker-test",
            "lost",
            1.0,
            2.0,
            ssh_user="deploy",
            effective_user="deploy",
        )

        class LostSupervisor:
            def get(self, requested_session_id: str) -> SessionRecord:
                self.requested_session_id = requested_session_id
                return record

            def request(self, *_args, **_kwargs):
                raise AssertionError("lost rediscovery must not request the dead worker")

        supervisor = LostSupervisor()
        server = object.__new__(BrokerServer)
        server.supervisor = supervisor  # type: ignore[assignment]

        result = server._handle_request(  # noqa: SLF001 - broker dispatch contract
            "session.rediscover",
            {"session_id": session_id},
        )

        self.assertEqual(supervisor.requested_session_id, session_id)
        self.assertEqual(result["state"], "lost")
        self.assertEqual(result["pid"], 1234)
        self.assertTrue(result["rediscovered"])
        self.assertFalse(result["command_retried"])

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
        self.assertEqual(
            connection.receive_timeout,
            LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS,
        )
        self.assertTrue(connection.closed)
        self.assertIsNone(client.connection)

    def test_broker_disconnect_after_read_is_unavailable_not_unknown(self) -> None:
        client = object.__new__(BrokerClient)
        connection = _FailingConnection()
        client.connection = connection  # type: ignore[assignment]
        client._lock = threading.Lock()  # noqa: SLF001

        with self.assertRaises(BrokerUnavailable):
            client.request("session.files", {"action": "read_text"})

        self.assertEqual(
            connection.receive_timeout,
            LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS,
        )
        self.assertTrue(connection.closed)

    def test_broker_handshake_receives_the_connection_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = RuntimeDirectory(Path(temporary) / "runtime")
            runtime.prepare()
            runtime.write_json(
                runtime.broker_status_path,
                {
                    "pid": 123,
                    "pipe": r"\\.\pipe\codex-serverops-fixture",
                    "protocol_version": BROKER_PROTOCOL_VERSION,
                    "instance_token": "x" * 32,
                    "started_at": 1.0,
                },
            )
            connection = _FailingConnection()
            with (
                patch(
                    "codex_serverops_mcp.broker.client.connect_named_pipe",
                    return_value=connection,
                ),
                patch("codex_serverops_mcp.broker.client.client_handshake") as handshake,
            ):
                client = BrokerClient(runtime.path, timeout=1.25)
                client.close()

            handshake.assert_called_once_with(connection, "x" * 32, timeout=1.25)

    def test_quick_broker_request_has_a_bounded_response_deadline(self) -> None:
        client = object.__new__(BrokerClient)
        connection = _FailingConnection()
        client.connection = connection  # type: ignore[assignment]
        client._lock = threading.Lock()  # noqa: SLF001

        with self.assertRaises(BrokerUnavailable):
            client.request("broker.ping")

        self.assertEqual(
            connection.receive_timeout,
            DEFAULT_BROKER_RESPONSE_TIMEOUT_SECONDS,
        )

    def test_sudo_acquire_allows_local_auth_without_shortening_remote_timeout(self) -> None:
        self.assertEqual(
            broker_response_timeout("session.elevation", {"action": "acquire"}),
            LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS,
        )
        self.assertLess(
            WORKER_LONG_OPERATION_TIMEOUT_SECONDS,
            LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS,
        )
        self.assertLess(LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS, 3_730)

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
