from __future__ import annotations

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from codex_serverops_mcp.bootstrap import LocalStateBootstrapper, LocalStatePaths
from codex_serverops_mcp.config import TomlProfileRepository
from codex_serverops_mcp.config.model import (
    Authentication,
    ConnectionType,
    ServerOpsConfig,
    ServerProfile,
)
from codex_serverops_mcp.errors import ConfigurationError, ConfigVersionError


class BootstrapTests(unittest.TestCase):
    def _paths(self, root: Path) -> LocalStatePaths:
        return LocalStatePaths.from_app_dir(root / "codex-serverops-mcp")

    def test_explicit_runtime_path_uses_an_isolated_state_root(self) -> None:
        runtime = Path("C:/isolated/serverops/runtime")
        paths = LocalStatePaths.from_runtime_path(runtime)
        self.assertEqual(paths.runtime_dir, runtime)
        self.assertEqual(paths.app_dir, runtime.parent)
        self.assertEqual(paths.config_file, runtime.parent / "config.toml")

    def test_first_run_creates_only_managed_empty_state_and_second_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            first = LocalStateBootstrapper(paths).ensure()
            managed = {
                paths.app_dir,
                paths.config_file,
                paths.config_file.with_name("config.toml.lock"),
                paths.runtime_dir,
                paths.runtime_dir / "workers",
                paths.runtime_dir / "setup",
                paths.audit_dir,
                paths.audit_dir / ".audit.lock",
                paths.migrations_dir,
                paths.state_file,
                paths.bootstrap_lock,
            }
            self.assertTrue(all(path.exists() for path in managed))
            self.assertTrue(first.config_created)
            self.assertFalse(first.config_migrated)
            self.assertEqual(TomlProfileRepository(paths.config_file).load().config.profiles, {})
            stable = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in (paths.config_file, paths.state_file)
            }

            second = LocalStateBootstrapper(paths).ensure()

            self.assertFalse(second.config_created)
            self.assertFalse(second.config_migrated)
            self.assertEqual(
                stable,
                {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in (paths.config_file, paths.state_file)
                },
            )
            self.assertEqual(tuple(paths.migrations_dir.iterdir()), ())

    def test_parallel_first_run_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            with ThreadPoolExecutor(max_workers=4) as executor:
                reports = tuple(
                    executor.map(lambda _index: LocalStateBootstrapper(paths).ensure(), range(4))
                )
            self.assertEqual(sum(report.config_created for report in reports), 1)
            self.assertEqual(TomlProfileRepository(paths.config_file).load().config.profiles, {})

    def test_legacy_config_is_backed_up_once_and_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            paths.app_dir.mkdir()
            original = b"[profiles]\n"
            paths.config_file.write_bytes(original)

            first = LocalStateBootstrapper(paths).ensure()
            second = LocalStateBootstrapper(paths).ensure()

            self.assertTrue(first.config_migrated)
            self.assertIsNotNone(first.migration_backup)
            assert first.migration_backup is not None
            self.assertEqual(first.migration_backup.read_bytes(), original)
            self.assertFalse(second.config_migrated)
            self.assertEqual(len(tuple(paths.migrations_dir.iterdir())), 1)
            self.assertIn(b"schema_version = 1", paths.config_file.read_bytes())

    def test_public_010_state_is_adopted_without_rewriting_profiles_or_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            paths.app_dir.mkdir()
            repository = TomlProfileRepository(paths.config_file)
            repository.save(
                ServerOpsConfig(
                    profiles={
                        "existing": ServerProfile(
                            display_name="Existing 0.1.0 profile",
                            connection_type=ConnectionType.DIRECT,
                            authentication=Authentication.OPENSSH,
                            host="192.0.2.10",
                            port=22,
                            user="operator",
                        )
                    }
                )
            )
            paths.audit_dir.mkdir()
            audit = paths.audit_dir / "2026-07-18.jsonl"
            audit.write_bytes(b'{"event":"existing-0.1.0-audit"}\n')
            before = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in (paths.config_file, audit)
            }

            report = LocalStateBootstrapper(paths).ensure()

            self.assertFalse(report.config_created)
            self.assertFalse(report.config_migrated)
            self.assertEqual(
                before,
                {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in (paths.config_file, audit)
                },
            )
            self.assertIn("existing", repository.load().config.profiles)
            self.assertTrue(paths.state_file.exists())

    def test_future_config_and_unmanaged_child_are_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            paths.app_dir.mkdir()
            foreign = paths.app_dir / "customer-note.txt"
            foreign.write_bytes(b"leave me alone")
            future = b"schema_version = 999\n"
            paths.config_file.write_bytes(future)

            with self.assertRaises(ConfigVersionError):
                LocalStateBootstrapper(paths).ensure()

            self.assertEqual(paths.config_file.read_bytes(), future)
            self.assertEqual(foreign.read_bytes(), b"leave me alone")

    def test_failed_post_write_verification_restores_migration_preimage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            paths.app_dir.mkdir()
            paths.migrations_dir.mkdir()
            original = b"[profiles]\n"
            paths.config_file.write_bytes(original)
            repository = TomlProfileRepository(paths.config_file)
            load = repository._load_unlocked
            calls = 0

            def fail_second_load():
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected verification failure")
                return load()

            with (
                patch.object(repository, "_load_unlocked", side_effect=fail_second_load),
                self.assertRaisesRegex(ConfigurationError, "rolled back"),
            ):
                repository.initialize_or_migrate(
                    migration_backup_dir=paths.migrations_dir
                )
            self.assertEqual(paths.config_file.read_bytes(), original)

    def test_managed_directory_replaced_by_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            paths.app_dir.mkdir()
            paths.runtime_dir.write_bytes(b"not a directory")
            with self.assertRaisesRegex(ConfigurationError, "must be a directory"):
                LocalStateBootstrapper(paths).ensure()
            self.assertEqual(paths.runtime_dir.read_bytes(), b"not a directory")

    @unittest.skipUnless(os.name == "nt", "current-user DACL contract is Windows-only")
    def test_every_managed_path_is_current_user_only(self) -> None:
        from codex_serverops_mcp.ipc.security import inspect_path_security

        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            LocalStateBootstrapper(paths).ensure()
            managed = (
                paths.app_dir,
                paths.config_file,
                paths.config_file.with_name("config.toml.lock"),
                paths.runtime_dir,
                paths.runtime_dir / "workers",
                paths.runtime_dir / "setup",
                paths.audit_dir,
                paths.audit_dir / ".audit.lock",
                paths.migrations_dir,
                paths.state_file,
                paths.bootstrap_lock,
            )
            for path in managed:
                with self.subTest(path=path):
                    self.assertTrue(inspect_path_security(str(path)).current_user_only)

            legacy_root = Path(directory) / "legacy" / "codex-serverops-mcp"
            legacy_paths = self._paths(legacy_root.parent)
            legacy_paths.app_dir.mkdir(parents=True)
            legacy_paths.config_file.write_bytes(b"[profiles]\n")
            report = LocalStateBootstrapper(legacy_paths).ensure()
            assert report.migration_backup is not None
            self.assertTrue(
                inspect_path_security(str(report.migration_backup)).current_user_only
            )


if __name__ == "__main__":
    unittest.main()
