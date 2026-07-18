from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerProfile,
)
from codex_serverops_mcp.security import AuditLogger, ProfileAudit, SetupAuditStatus


class FailingAuditLogger:
    def record(self, **_parameters: object):
        raise OSError("audit unavailable")


def sensitive_profile() -> ServerProfile:
    return ServerProfile(
        display_name="Customer production",
        connection_type=ConnectionType.DIRECT,
        authentication=Authentication.OPENSSH,
        host="203.0.113.77",
        port=2222,
        user="private-user",
        identity_file="C:/Users/private/.ssh/customer_key",
        allowed_roots=("/srv/customer/private",),
        allow_terminal=True,
        allow_file_read=True,
        allow_file_write=False,
        elevation_mode=ElevationMode.INTERACTIVE,
        allow_root_session=True,
        environment="production",
    )


class ProfileAuditTests(unittest.TestCase):
    def test_profile_event_contains_only_allowlisted_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = ProfileAudit(AuditLogger(Path(directory)))

            status = audit.record("profile_created", "prod", profile=sensitive_profile())

            line = next(Path(directory).glob("*.jsonl")).read_text(encoding="utf-8")
            event = json.loads(line)
            self.assertTrue(status.logged)
            self.assertEqual(event["profile_name"], "prod")
            self.assertEqual(event["connection_type"], "direct")
            self.assertEqual(event["authentication"], "openssh")
            self.assertEqual(event["environment"], "production")
            self.assertTrue(event["terminal_enabled"])
            self.assertTrue(event["file_read_enabled"])
            self.assertFalse(event["file_write_enabled"])
            self.assertEqual(event["elevation_mode"], "interactive")
            self.assertTrue(event["root_session_enabled"])
            for forbidden in (
                "203.0.113.77",
                "private-user",
                "customer_key",
                "/srv/customer/private",
                "Customer production",
            ):
                self.assertNotIn(forbidden, line)

    def test_audit_failure_returns_false_without_raising(self) -> None:
        audit = ProfileAudit(FailingAuditLogger())  # type: ignore[arg-type]

        status = audit.record("profile_created", "prod", profile=sensitive_profile())

        self.assertFalse(status.logged)

    def test_free_text_environment_is_redacted_to_a_bounded_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = ProfileAudit(AuditLogger(Path(directory)))
            profile = replace(
                sensitive_profile(),
                environment="password=hunter2 203.0.113.9 customer-code",
            )

            audit.record("profile_updated", "prod", profile=profile)

            line = next(Path(directory).glob("*.jsonl")).read_text(encoding="utf-8")
            event = json.loads(line)
            self.assertEqual(event["environment"], "custom")
            self.assertNotIn("hunter2", line)
            self.assertNotIn("203.0.113.9", line)
            self.assertNotIn("customer-code", line)

    def test_combined_status_preserves_prior_audit_failure(self) -> None:
        result = SetupAuditStatus(True).attach({"audit": {"logged": False}, "status": "ok"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["audit"], {"logged": False})


if __name__ == "__main__":
    unittest.main()
