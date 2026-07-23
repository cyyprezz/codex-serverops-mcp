from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt", "worker processes use Windows named pipes")
class WorkerProcessLifecycleTests(unittest.TestCase):
    def test_authenticated_broker_disconnect_terminates_worker_and_removes_status(self) -> None:
        from codex_serverops_mcp.ipc.errors import IpcClosed
        from codex_serverops_mcp.runtime import RuntimeDirectory
        from codex_serverops_mcp.worker.process import run_worker

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                pass

            @staticmethod
            def receive(*_args: object, **_kwargs: object) -> None:
                raise IpcClosed("authenticated broker disconnected")

        class Listener:
            def __init__(self, _pipe: str) -> None:
                self.accept_count = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                pass

            def accept(self) -> Connection:
                self.accept_count += 1
                if self.accept_count != 1:
                    raise AssertionError("orphaned worker waited for an unadoptable broker")
                return Connection()

        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "runtime"
            session_id = "sess-0123456789abcdef"
            handler = SimpleNamespace(service=SimpleNamespace(close=lambda: None))
            with (
                patch.dict(os.environ, {"SERVEROPS_WORKER_TOKEN": "x" * 32}),
                patch("codex_serverops_mcp.worker.process.NamedPipeListener", Listener),
                patch("codex_serverops_mcp.worker.process.server_handshake"),
                patch(
                    "codex_serverops_mcp.worker.process.WorkerProtocolHandler",
                    return_value=handler,
                ),
            ):
                self.assertEqual(
                    run_worker(session_id, "test-profile", runtime_path),
                    0,
                )
            self.assertFalse(
                RuntimeDirectory(runtime_path).worker_status_path(session_id).exists()
            )


if __name__ == "__main__":
    unittest.main()
