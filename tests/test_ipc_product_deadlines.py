from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from codex_serverops_mcp.broker.server import BrokerServer
from codex_serverops_mcp.ipc.constants import IPC_HANDSHAKE_TIMEOUT_SECONDS
from codex_serverops_mcp.ipc.errors import IpcClosed, IpcTimeout
from codex_serverops_mcp.worker.process import run_worker


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        pass


class _Listener:
    def __init__(self) -> None:
        self.accept_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def accept(self):
        self.accept_count += 1
        if self.accept_count == 1:
            return _Connection()
        raise IpcClosed("fixture complete")


class ProductIpcDeadlineTests(unittest.TestCase):
    def test_broker_server_applies_a_handshake_deadline(self) -> None:
        server = object.__new__(BrokerServer)
        server.instance_token = "fixture-token"
        server._stop = threading.Event()  # noqa: SLF001
        server._thread_lock = threading.Lock()  # noqa: SLF001
        server._client_threads = set()  # noqa: SLF001
        connection = _Connection()

        with patch(
            "codex_serverops_mcp.broker.server.server_handshake",
            side_effect=IpcTimeout("fixture timeout"),
        ) as handshake:
            server._serve_client(connection)  # noqa: SLF001

        handshake.assert_called_once_with(
            connection,
            "fixture-token",
            timeout=IPC_HANDSHAKE_TIMEOUT_SECONDS,
        )

    def test_worker_server_applies_a_handshake_deadline(self) -> None:
        listener = _Listener()
        handler = Mock()
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"SERVEROPS_WORKER_TOKEN": "fixture-token"}),
            patch(
                "codex_serverops_mcp.worker.process.NamedPipeListener",
                return_value=listener,
            ),
            patch(
                "codex_serverops_mcp.worker.process.WorkerProtocolHandler",
                return_value=handler,
            ),
            patch(
                "codex_serverops_mcp.worker.process.server_handshake",
                side_effect=IpcTimeout("fixture timeout"),
            ) as handshake,
        ):
            result = run_worker(
                "sess-0123456789abcdef",
                "fixture-profile",
                Path(temporary) / "runtime",
            )

        self.assertEqual(result, 0)
        handshake.assert_called_once_with(
            unittest.mock.ANY,
            "fixture-token",
            expected_role="broker",
            timeout=IPC_HANDSHAKE_TIMEOUT_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
