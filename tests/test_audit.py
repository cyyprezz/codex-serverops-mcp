from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from codex_serverops_mcp.security import AuditLogger, default_audit_path


class AuditLoggerTests(unittest.TestCase):
    def test_default_path_uses_local_app_data(self) -> None:
        self.assertEqual(
            default_audit_path(local_app_data="C:/Users/example/AppData/Local"),
            Path("C:/Users/example/AppData/Local/codex-serverops-mcp/audit"),
        )

    def test_jsonl_schema_redacts_command_and_omits_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 7, 18, 4, 30, tzinfo=UTC)
            logger = AuditLogger(Path(directory), now=lambda: now)
            response = {
                "status": "completed",
                "session_id": "sess-0123456789abcdef",
                "profile_name": "prod",
                "ssh_user": "deploy",
                "effective_user": "root",
                "exit_code": 7,
                "duration_ms": 100,
                "truncated": True,
                "elevated": True,
                "output": "file content that must never be audited",
            }

            written = logger.record(
                tool="server_elevation",
                action="exec",
                result=response,
                duration_ms=125,
                command="curl -H 'Authorization: Bearer abcdefghijklmnop' example.test",
            )

            line = (Path(directory) / "2026-07-18.jsonl").read_text(encoding="utf-8")
            event = json.loads(line)
            self.assertTrue(written.logged)
            self.assertTrue(written.command_redacted)
            self.assertNotIn("abcdefghijklmnop", line)
            self.assertNotIn("file content", line)
            self.assertEqual(event["schema_version"], 1)
            self.assertEqual(event["effective_user"], "root")
            self.assertEqual(event["exit_code"], 7)
            self.assertEqual(event["duration_ms"], 125)
            self.assertTrue(event["output_truncated"])
            self.assertTrue(event["elevated"])
            self.assertEqual(len(event["command_sha256"]), 64)

    def test_error_event_has_controlled_status_and_no_command_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logger = AuditLogger(Path(directory))
            logger.record(
                tool="server_connection",
                action="open",
                result=None,
                error_status="connection_failed",
                duration_ms=2,
                profile="prod",
            )
            path = next(Path(directory).glob("*.jsonl"))
            event = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(event["result_status"], "connection_failed")
            self.assertIsNone(event["command_preview"])
            self.assertIsNone(event["command_sha256"])


if __name__ == "__main__":
    unittest.main()
