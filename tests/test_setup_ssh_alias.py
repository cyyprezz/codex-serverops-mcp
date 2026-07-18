from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from codex_serverops_mcp.setup.ssh_alias import (
    SshAliasSpec,
    apply_ssh_alias_change,
    plan_ssh_alias_change,
)


class SetupSshAliasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.identity = self.root / "identity"
        self.identity.write_text("test", encoding="utf-8")
        self.spec = SshAliasSpec(
            "serverops-test",
            "192.0.2.10",
            "deploy",
            22,
            self.identity,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_prepends_managed_alias_without_reformatting_existing_bytes(self) -> None:
        path = self.root / "config"
        original = b"Host existing\r\n    HostName 192.0.2.5\r\n"
        path.write_bytes(original)

        change = plan_ssh_alias_change(path, self.spec)

        self.assertTrue(change.updated.endswith(original))
        self.assertIn(b"Host serverops-test\r\n", change.updated)

    def test_unmanaged_exact_alias_is_not_overwritten(self) -> None:
        path = self.root / "config"
        path.write_text("Host\tserverops-test\n  HostName example.test\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "unmanaged"):
            plan_ssh_alias_change(path, self.spec)

    def test_apply_keeps_exact_backup_and_validates_before_and_after_write(self) -> None:
        path = self.root / "config"
        original = b"Host existing\n  HostName 192.0.2.5\n"
        path.write_bytes(original)
        change = plan_ssh_alias_change(path, self.spec)
        validated: list[bytes] = []

        def validator(candidate: Path, _spec: SshAliasSpec) -> None:
            validated.append(candidate.read_bytes())

        result = apply_ssh_alias_change(
            path,
            change,
            validator=validator,
            now=lambda: datetime(2026, 7, 18, tzinfo=UTC),
        )

        self.assertEqual(path.read_bytes(), change.updated)
        assert result.backup_path is not None
        self.assertEqual(result.backup_path.read_bytes(), original)
        self.assertEqual(validated, [change.updated, change.updated])

    def test_post_write_validation_failure_restores_original(self) -> None:
        path = self.root / "config"
        original = b"Host existing\n  HostName 192.0.2.5\n"
        path.write_bytes(original)
        change = plan_ssh_alias_change(path, self.spec)
        calls = 0

        def validator(_candidate: Path, _spec: SshAliasSpec) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic post-write failure")

        with self.assertRaisesRegex(RuntimeError, "rolled back"):
            apply_ssh_alias_change(path, change, validator=validator)

        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
