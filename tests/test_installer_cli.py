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
            self.assertFalse((root / "local" / "codex-serverops-mcp").exists())
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
            self.assertIn(str(wheel.resolve()).replace("\\", "\\\\"), config)

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

    def test_setup_twice_is_idempotent_and_preserves_both_client_configs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            }
            codex = root / "user" / ".codex" / "config.toml"
            claude = root / "user" / ".claude" / "settings.json"
            codex.parent.mkdir(parents=True)
            claude.parent.mkdir(parents=True)
            codex.write_text("[features]\nforeign = true\n", encoding="utf-8")
            claude.write_text('{"foreign":true}\n', encoding="utf-8")
            client_snapshot = {path: path.read_bytes() for path in (codex, claude)}
            with (
                patch.dict(os.environ, environment, clear=True),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(run(["setup"]), 0)
                app = root / "local" / "codex-serverops-mcp"
                stable = {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in (app / "config.toml", app / "state.json")
                }
                self.assertEqual(run(["setup"]), 0)
            self.assertEqual(
                stable,
                {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in stable
                },
            )
            self.assertEqual(client_snapshot, {path: path.read_bytes() for path in client_snapshot})

    def test_client_selector_defaults_to_codex_and_accepts_claude(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["check"]).client, "codex")
        self.assertEqual(parser.parse_args(["doctor", "--client", "claude"]).client, "claude")

    def test_plugin_only_uninstall_is_idempotent_and_does_not_recreate_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            }
            controller = Mock()
            controller.inspect.return_value = BrokerTaskStatus(
                "ServerOps test task", False, False, False
            )
            with (
                patch.dict(os.environ, environment, clear=True),
                patch(
                    "codex_serverops_mcp.installer.cli.BrokerTaskController.connect",
                    return_value=controller,
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run(["uninstall"]), 0)
            self.assertFalse((root / "local" / "codex-serverops-mcp").exists())
            self.assertFalse((root / "user" / ".codex" / "config.toml").exists())

    def test_uninstall_preserves_data_until_remove_data_is_explicitly_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            }
            controller = Mock()
            controller.inspect.return_value = BrokerTaskStatus(
                "ServerOps test task", False, False, False
            )
            controller.remove.return_value = False
            with (
                patch.dict(os.environ, environment, clear=True),
                patch(
                    "codex_serverops_mcp.installer.cli.BrokerTaskController.connect",
                    return_value=controller,
                ),
                patch("codex_serverops_mcp.installer.cli._shutdown_broker"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(run(["setup"]), 0)
                app = root / "local" / "codex-serverops-mcp"
                audit = app / "audit" / "existing.jsonl"
                audit.write_text('{"event":"keep"}\n', encoding="utf-8")
                config_before = (app / "config.toml").read_bytes()

                self.assertEqual(run(["uninstall", "--apply", "--yes"]), 0)
                self.assertEqual((app / "config.toml").read_bytes(), config_before)
                self.assertEqual(audit.read_text(encoding="utf-8"), '{"event":"keep"}\n')

                self.assertEqual(run(["uninstall", "--remove-data"]), 0)
                self.assertTrue(app.exists())
                self.assertEqual(
                    run(["uninstall", "--remove-data", "--apply", "--yes"]),
                    0,
                )
                self.assertFalse(app.exists())

    def test_update_uses_client_neutral_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "LOCALAPPDATA": str(root / "local"),
                "USERPROFILE": str(root / "user"),
            }
            report = Mock(succeeded=True)
            report.checks = ()
            report.status = "pass"
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("codex_serverops_mcp.installer.cli.LocalChecker") as checker,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                checker.return_value.run.return_value = report
                self.assertEqual(run(["update"]), 0)
            checker.return_value.run.assert_called_once_with(
                include_broker=False,
                client="core",
            )


if __name__ == "__main__":
    unittest.main()
