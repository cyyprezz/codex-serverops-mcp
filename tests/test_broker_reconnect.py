from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "broker processes use Windows named pipes")
class BrokerReconnectTests(unittest.TestCase):
    def test_new_client_rediscovers_broker_owned_worker(self) -> None:
        from codex_serverops_mcp.broker.client import BrokerClient
        from codex_serverops_mcp.broker.errors import BrokerAlreadyRunning
        from codex_serverops_mcp.broker.server import BrokerServer
        from codex_serverops_mcp.runtime import RuntimeDirectory

        with tempfile.TemporaryDirectory() as temporary:
            runtime_path = Path(temporary) / "runtime"
            runtime = RuntimeDirectory(runtime_path)
            process = self._start_broker(runtime_path)
            try:
                self._wait_for_path(runtime.broker_status_path, process)
                with self.assertRaises(BrokerAlreadyRunning):
                    BrokerServer(Path(temporary) / "other-runtime")

                with BrokerClient(runtime_path) as first_client:
                    broker_pid = first_client.request("broker.ping")["pid"]
                    created = first_client.request(
                        "session.create", {"profile_name": "test-profile"}
                    )

                session_id = str(created["session_id"])
                worker_pid = created["worker_pid"]
                worker_status = runtime.worker_status_path(session_id)
                self.assertTrue(worker_status.exists())

                with BrokerClient(runtime_path) as second_client:
                    self.assertEqual(second_client.request("broker.ping")["pid"], broker_pid)
                    sessions = second_client.request("session.list")["sessions"]
                    self.assertEqual(len(sessions), 1)
                    self.assertEqual(sessions[0]["session_id"], session_id)
                    self.assertEqual(sessions[0]["worker_pid"], worker_pid)
                    second_client.request("session.close", {"session_id": session_id})
                    self.assertFalse(worker_status.exists())
                    second_client.request("broker.shutdown")

                process.wait(timeout=10)
                self.assertEqual(process.returncode, 0, self._stderr(process))
                self.assertFalse(runtime.broker_status_path.exists())
            finally:
                self._stop_process(process)

    @staticmethod
    def _start_broker(runtime_path: Path) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "codex_serverops_mcp.broker.server",
                "--runtime",
                str(runtime_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    @staticmethod
    def _wait_for_path(path: Path, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if path.exists():
                return
            if process.poll() is not None:
                raise AssertionError(
                    f"broker exited during startup with code {process.returncode}: "
                    f"{BrokerReconnectTests._stderr(process)}"
                )
            time.sleep(0.05)
        raise AssertionError("broker did not publish startup status")

    @staticmethod
    def _stderr(process: subprocess.Popen[str]) -> str:
        if process.stderr is None:
            return ""
        content = process.stderr.read()
        process.stderr.close()
        return content

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stderr is not None and not process.stderr.closed:
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
