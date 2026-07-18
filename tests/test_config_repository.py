from __future__ import annotations

import tempfile
import time
import unittest
from multiprocessing import get_context
from pathlib import Path

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ServerProfile,
    TomlProfileRepository,
    default_config_path,
)
from codex_serverops_mcp.config.locking import InterProcessFileLock
from codex_serverops_mcp.errors import ConfigConflictError, ConfigLockTimeout


def _hold_lock(lock_path: str, ready_path: str, release_path: str) -> None:
    with InterProcessFileLock(Path(lock_path), timeout=2):
        Path(ready_path).touch()
        deadline = time.monotonic() + 10
        while not Path(release_path).exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("test release marker was not created")
            time.sleep(0.02)


class ConfigRepositoryTests(unittest.TestCase):
    @staticmethod
    def _profile(display_name: str = "Test Server") -> ServerProfile:
        return ServerProfile(
            display_name=display_name,
            connection_type=ConnectionType.DIRECT,
            authentication=Authentication.INTERACTIVE_PASSWORD,
            host="192.0.2.10",
            port=22,
            user="deploy",
        )

    def test_default_path_uses_local_app_data(self) -> None:
        path = default_config_path("C:/Users/example/AppData/Local")
        self.assertEqual(
            path,
            Path("C:/Users/example/AppData/Local/codex-serverops-mcp/config.toml"),
        )

    def test_put_load_and_remove_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nested" / "config.toml"
            repository = TomlProfileRepository(path)
            empty = repository.load()

            saved = repository.put_profile(
                "test-server",
                self._profile(),
                expected_hash=empty.content_hash,
            )
            self.assertEqual(repository.load(), saved)
            self.assertEqual(saved.config.profiles["test-server"].host, "192.0.2.10")
            self.assertFalse(any(path.parent.glob(".*.tmp")))

            removed = repository.remove_profile(
                "test-server",
                expected_hash=saved.content_hash,
            )
            self.assertEqual(dict(removed.config.profiles), {})
            self.assertFalse(any(path.parent.glob(".*.tmp")))

    def test_stale_hash_prevents_lost_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.toml"
            repository = TomlProfileRepository(path)
            initial = repository.load()
            first = repository.put_profile("first", self._profile("First"))

            with self.assertRaises(ConfigConflictError):
                repository.put_profile(
                    "second",
                    self._profile("Second"),
                    expected_hash=initial.content_hash,
                )

            self.assertEqual(repository.load(), first)

    def test_explicit_migration_rewrites_legacy_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.toml"
            path.write_text(
                """
[profiles.demo]
display_name = "Demo"
connection_type = "direct"
authentication = "interactive_password"
host = "192.0.2.10"
port = 22
user = "deploy"
sudo_mode = "disabled"
""",
                encoding="utf-8",
            )
            repository = TomlProfileRepository(path)

            snapshot, migrated = repository.migrate()

            self.assertTrue(migrated)
            self.assertIn("schema_version = 1", path.read_text(encoding="utf-8"))
            self.assertNotIn("sudo_mode", path.read_text(encoding="utf-8"))
            self.assertEqual(repository.load(), snapshot)

    def test_lock_timeout_is_enforced_across_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "config.toml"
            ready = root / "ready"
            release = root / "release"
            repository = TomlProfileRepository(path, lock_timeout=0.1)
            context = get_context("spawn")
            process = context.Process(
                target=_hold_lock,
                args=(str(repository.lock_path), str(ready), str(release)),
            )
            process.start()
            deadline = time.monotonic() + 5
            while not ready.exists() and process.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            try:
                self.assertTrue(ready.exists(), "child process did not acquire the lock")
                with self.assertRaises(ConfigLockTimeout):
                    repository.load()
            finally:
                release.touch()
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            self.assertEqual(process.exitcode, 0)


if __name__ == "__main__":
    unittest.main()
