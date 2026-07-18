from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_serverops_mcp.spike import cli


class SpikeSecretCleanupTests(unittest.TestCase):
    def _tool_paths(self, project_root: Path) -> tuple[Path, Path]:
        ssh = project_root / "ssh.exe"
        ssh_keygen = project_root / "ssh-keygen.exe"
        ssh.touch()
        ssh_keygen.touch()
        return ssh, ssh_keygen

    @staticmethod
    def _generate_key(_ssh_keygen: Path, identity: Path, _passphrase: str) -> None:
        identity.write_text("disposable-private-key", encoding="utf-8")
        identity.with_suffix(".pub").write_text("disposable-public-key", encoding="utf-8")

    @staticmethod
    def _assert_secrets_removed(test: unittest.TestCase, runtime: Path) -> None:
        for name in ("password", "passphrase", "id_ed25519", "id_ed25519.pub"):
            test.assertFalse((runtime / name).exists(), name)

    def test_secret_material_is_removed_when_fixture_start_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            ssh, ssh_keygen = self._tool_paths(project_root)
            runtime = project_root / ".spike-runtime"

            with (
                patch.object(cli.shutil, "which", side_effect=[str(ssh), str(ssh_keygen)]),
                patch.object(cli, "generate_protected_ed25519_key", self._generate_key),
                patch.object(cli, "_start_container", side_effect=RuntimeError("fixture failed")),
                self.assertRaisesRegex(RuntimeError, "fixture failed"),
            ):
                cli.run_spike(project_root)

            self._assert_secrets_removed(self, runtime)

    def test_secret_material_is_removed_when_session_open_is_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            ssh, ssh_keygen = self._tool_paths(project_root)
            runtime = project_root / ".spike-runtime"

            with (
                patch.object(cli.shutil, "which", side_effect=[str(ssh), str(ssh_keygen)]),
                patch.object(cli, "generate_protected_ed25519_key", self._generate_key),
                patch.object(cli, "_start_container", return_value=2222),
                patch.object(cli, "_stop_container") as stop_container,
                patch.object(
                    cli.SshSpikeSession,
                    "open",
                    side_effect=RuntimeError("authentication cancelled"),
                ),
                self.assertRaisesRegex(RuntimeError, "authentication cancelled"),
            ):
                cli.run_spike(project_root, visible_auth=True)

            stop_container.assert_called_once_with()
            self._assert_secrets_removed(self, runtime)


if __name__ == "__main__":
    unittest.main()
