from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from codex_serverops_mcp import PACKAGE_VERSION
from codex_serverops_mcp.broker.task_model import BrokerTaskSpec, BrokerTaskStatus
from codex_serverops_mcp.installer.cli import build_parser, run


class InstallerCliTests(unittest.TestCase):
    def test_parser_exposes_exact_required_commands(self) -> None:
        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if action.__class__.__name__ == "_SubParsersAction"
        )
        self.assertEqual(
            set(subparsers.choices),
            {"setup", "check", "doctor", "codex-config", "update", "uninstall"},
        )

    def test_codex_config_is_preview_only_then_explicitly_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            }
            path = root / "user" / ".codex" / "config.toml"
            output = io.StringIO()
            with (
                patch.dict(os.environ, environment, clear=True),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(run(["codex-config"]), 0)
            self.assertFalse(path.exists())
            self.assertIn(f"codex-serverops-mcp=={PACKAGE_VERSION}", output.getvalue())

            with (
                patch.dict(os.environ, environment, clear=True),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(run(["codex-config", "--apply", "--yes"]), 0)
            self.assertIn(
                f"codex-serverops-mcp=={PACKAGE_VERSION}",
                path.read_text(encoding="utf-8"),
            )

    def test_yes_without_apply_fails_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run(["codex-config", "--yes"]), 1)
            self.assertFalse((root / "user" / ".codex" / "config.toml").exists())

    def test_codex_config_can_apply_an_exact_local_development_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            }
            wheel = root / f"codex_serverops_mcp-{PACKAGE_VERSION}-py3-none-any.whl"
            metadata = (
                "Metadata-Version: 2.4\n"
                "Name: codex-serverops-mcp\n"
                f"Version: {PACKAGE_VERSION}\n"
            )
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    f"codex_serverops_mcp-{PACKAGE_VERSION}.dist-info/METADATA",
                    metadata,
                )
            with (
                patch.dict(os.environ, environment, clear=True),
                patch(
                    "codex_serverops_mcp.installer.codex_config.shutil.which",
                    return_value=str(root / "uvx.exe"),
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    run(
                        [
                            "codex-config",
                            "--development-wheel",
                            str(wheel),
                            "--development-python",
                            sys.executable,
                            "--apply",
                            "--yes",
                        ]
                    ),
                    0,
                )
            config = (root / "user" / ".codex" / "config.toml").read_text(
                encoding="utf-8"
            )
            self.assertIn('args = ["--python"', config)
            self.assertIn('"--offline", "--from"', config)
            self.assertIn(str(wheel).replace("\\", "\\\\"), config)

    def test_setup_broker_task_previews_then_explicitly_registers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            }
            spec = BrokerTaskSpec(
                executable=Path(__file__).resolve(),
                arguments=("serverops-broker",),
                source="unit-test",
            )
            missing = BrokerTaskStatus("ServerOps test task", False, False, False)
            installed = BrokerTaskStatus("ServerOps test task", True, True, False)
            controller = Mock(task_name="ServerOps test task")
            controller.inspect.return_value = missing
            controller.register.return_value = installed

            with (
                patch.dict(os.environ, environment, clear=True),
                patch(
                    "codex_serverops_mcp.installer.cli.production_broker_task_spec",
                    return_value=spec,
                ),
                patch(
                    "codex_serverops_mcp.installer.cli.BrokerTaskController.connect",
                    return_value=controller,
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(run(["setup", "--broker-task"]), 0)
                controller.register.assert_not_called()
                self.assertEqual(
                    run(["setup", "--broker-task", "--apply", "--yes"]),
                    0,
                )
            controller.register.assert_called_once_with(spec)

    def test_setup_rejects_apply_without_explicit_broker_task_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run(["setup", "--apply", "--yes"]), 1)
            self.assertFalse((root / "local" / "codex-serverops-mcp").exists())


if __name__ == "__main__":
    unittest.main()
