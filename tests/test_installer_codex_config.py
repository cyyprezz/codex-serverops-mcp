from __future__ import annotations

import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from codex_serverops_mcp.installer.codex_config import (
    BEGIN_MARKER,
    END_MARKER,
    apply_codex_config_change,
    inspect_managed_version,
    plan_codex_config_change,
)
from codex_serverops_mcp.installer.errors import InstallerError


class CodexConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / ".codex" / "config.toml"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_preview_is_checkout_free_and_exactly_pinned(self) -> None:
        change = plan_codex_config_change(self.path, "0.1.0")
        self.assertIn('command = "uvx"', change.preview)
        self.assertIn('"codex-serverops-mcp==0.1.0"', change.preview)
        self.assertIn('"codex-serverops-mcp"]', change.preview)
        self.assertNotIn("cwd =", change.preview)
        self.assertFalse(self.path.exists())

    def test_development_preview_pins_validated_local_wheel_offline(self) -> None:
        wheel = Path(self.temporary.name) / "codex_serverops_mcp-0.1.0-py3-none-any.whl"
        metadata = b"Metadata-Version: 2.4\nName: codex-serverops-mcp\nVersion: 0.1.0\n"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("codex_serverops_mcp-0.1.0.dist-info/METADATA", metadata)
        with patch(
            "codex_serverops_mcp.installer.codex_config.shutil.which",
            return_value=str(Path(self.temporary.name) / "uvx.exe"),
        ):
            change = plan_codex_config_change(
                self.path,
                "0.1.0",
                development_wheel=wheel,
                development_python=Path(sys.executable),
            )

        parsed = tomllib.loads(change.preview)
        server = parsed["mcp_servers"]["serverops"]
        self.assertEqual(
            server["args"],
            [
                "--python",
                str(Path(sys.executable).resolve()),
                "--offline",
                "--from",
                str(wheel.resolve()),
                "codex-serverops-mcp",
            ],
        )
        self.assertTrue(Path(server["command"]).is_absolute())
        self.assertNotIn("cwd", server)
        apply_codex_config_change(self.path, change)
        self.assertEqual(inspect_managed_version(self.path), "0.1.0")

    def test_development_preview_rejects_wrong_or_mismatched_wheel(self) -> None:
        wheel = Path(self.temporary.name) / "wrong.whl"
        wheel.write_bytes(b"not a wheel")
        with self.assertRaisesRegex(InstallerError, "validated"):
            plan_codex_config_change(
                self.path,
                "0.1.0",
                development_wheel=wheel,
                development_python=Path(sys.executable),
            )

    def test_development_preview_requires_explicit_python_312(self) -> None:
        wheel = Path(self.temporary.name) / "codex_serverops_mcp-0.1.0-py3-none-any.whl"
        metadata = b"Metadata-Version: 2.4\nName: codex-serverops-mcp\nVersion: 0.1.0\n"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("codex_serverops_mcp-0.1.0.dist-info/METADATA", metadata)
        with self.assertRaisesRegex(InstallerError, "explicit Python 3.12"):
            plan_codex_config_change(
                self.path,
                "0.1.0",
                development_wheel=wheel,
            )

    def test_apply_updates_only_managed_block_and_keeps_backup(self) -> None:
        self.path.parent.mkdir(parents=True)
        previous = "[features]\nexample = true\n"
        self.path.write_text(previous, encoding="utf-8")
        first = plan_codex_config_change(self.path, "0.1.0")
        apply_codex_config_change(self.path, first)
        installed = self.path.read_text(encoding="utf-8")
        self.assertEqual(installed.count(BEGIN_MARKER), 1)
        self.assertEqual(installed.count(END_MARKER), 1)
        self.assertEqual(inspect_managed_version(self.path), "0.1.0")
        self.assertEqual(
            self.path.with_name("config.toml.codex-serverops-mcp.backup").read_text(
                encoding="utf-8"
            ),
            previous,
        )
        tomllib.loads(installed)

        second = plan_codex_config_change(self.path, "0.1.1")
        apply_codex_config_change(self.path, second)
        updated = self.path.read_text(encoding="utf-8")
        self.assertIn("codex-serverops-mcp==0.1.1", updated)
        self.assertNotIn("codex-serverops-mcp==0.1.0", updated)

    def test_unmarked_conflict_and_ambiguous_markers_fail_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        unmarked = '[mcp_servers.serverops]\ncommand = "existing"\n'
        self.path.write_text(unmarked, encoding="utf-8")
        with self.assertRaisesRegex(InstallerError, "unmarked"):
            plan_codex_config_change(self.path, "0.1.0")
        self.assertEqual(self.path.read_text(encoding="utf-8"), unmarked)

        self.path.write_text(BEGIN_MARKER + "\n" + BEGIN_MARKER + "\n", encoding="utf-8")
        with self.assertRaisesRegex(InstallerError, "ambiguous"):
            plan_codex_config_change(self.path, "0.1.0")

    def test_external_change_after_preview_is_not_overwritten(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[features]\nexample = true\n", encoding="utf-8")
        change = plan_codex_config_change(self.path, "0.1.0")
        external = "[features]\nexternal = true\n"
        self.path.write_text(external, encoding="utf-8")
        with self.assertRaisesRegex(InstallerError, "changed after preview"):
            apply_codex_config_change(self.path, change)
        self.assertEqual(self.path.read_text(encoding="utf-8"), external)

    def test_remove_requires_and_removes_only_managed_block(self) -> None:
        apply_codex_config_change(
            self.path,
            plan_codex_config_change(self.path, "0.1.0"),
        )
        removal = plan_codex_config_change(self.path, "0.1.0", remove=True)
        apply_codex_config_change(self.path, removal)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "")
        no_op = plan_codex_config_change(self.path, "0.1.0", remove=True)
        apply_codex_config_change(self.path, no_op)
        self.assertEqual(no_op.previous, no_op.updated)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "")

    def test_failed_post_write_validation_rolls_back(self) -> None:
        self.path.parent.mkdir(parents=True)
        previous = "[features]\nexample = true\n"
        self.path.write_text(previous, encoding="utf-8")
        change = plan_codex_config_change(self.path, "0.1.0")
        with (
            patch(
                "codex_serverops_mcp.installer.codex_config.parse_codex_config",
                side_effect=[{}, InstallerError("injected")],
            ),
            self.assertRaisesRegex(InstallerError, "rolled back"),
        ):
            apply_codex_config_change(self.path, change)
        self.assertEqual(self.path.read_text(encoding="utf-8"), previous)


if __name__ == "__main__":
    unittest.main()
