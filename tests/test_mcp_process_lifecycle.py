from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "release runtime is Windows-only")
class McpProcessLifecycleTests(unittest.TestCase):
    def _start(self, root: Path) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment.update(
            {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
                "PYTHONPATH": str(ROOT / "src"),
                "PYTHONUNBUFFERED": "1",
            }
        )
        return subprocess.Popen(
            [sys.executable, "-m", "codex_serverops_mcp.server"],
            cwd=root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    @staticmethod
    def _close_process_streams(process: subprocess.Popen[str]) -> None:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    @staticmethod
    def _wait_for_bootstrap(root: Path, process: subprocess.Popen[str]) -> None:
        state = root / "local" / "codex-serverops-mcp" / "state.json"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if state.exists():
                return
            if process.poll() is not None:
                stderr = "" if process.stderr is None else process.stderr.read()
                raise AssertionError(f"MCP exited during bootstrap: {stderr}")
            time.sleep(0.05)
        raise AssertionError("MCP bootstrap did not complete")

    def test_eof_exits_cleanly_without_non_protocol_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = self._start(root)
            try:
                self._wait_for_bootstrap(root, process)
                assert process.stdin is not None
                process.stdin.close()
                process.wait(timeout=10)
                stdout = "" if process.stdout is None else process.stdout.read()
                stderr = "" if process.stderr is None else process.stderr.read()
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(stdout, "")
                self.assertNotIn("Traceback", stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                self._close_process_streams(process)

    def test_initialize_list_and_client_abort_emit_only_jsonrpc_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = self._start(root)
            try:
                self._wait_for_bootstrap(root, process)
                assert process.stdin is not None
                assert process.stdout is not None
                requests = (
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "serverops-rc", "version": "0.1.1"},
                        },
                    },
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                )
                responses: list[dict[str, object]] = []
                for request in requests:
                    process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
                    process.stdin.flush()
                    if "id" in request:
                        responses.append(json.loads(process.stdout.readline()))
                self.assertEqual([response["id"] for response in responses], [1, 2])
                tools = responses[1]["result"]["tools"]
                self.assertEqual(len(tools), 8)

                process.stdin.close()
                process.wait(timeout=10)
                remaining = process.stdout.read()
                for line in remaining.splitlines():
                    json.loads(line)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                self._close_process_streams(process)

    def test_sigterm_does_not_write_a_banner_or_traceback_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = self._start(root)
            try:
                self._wait_for_bootstrap(root, process)
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=10)
                stdout = "" if process.stdout is None else process.stdout.read()
                self.assertEqual(stdout, "")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                self._close_process_streams(process)


if __name__ == "__main__":
    unittest.main()
