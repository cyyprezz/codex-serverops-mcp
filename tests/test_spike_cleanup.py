from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codex_serverops_mcp.spike import cli
from codex_serverops_mcp.spike import session as spike_session


class FakeReadyTerminal:
    backend_name = "conpty"

    def __init__(self, **_kwargs: object) -> None:
        self.running = True
        self.writes: list[bytes] = []
        self._read = False

    def start(self, _arguments: object) -> None:
        return

    def wait_for_data(self, _cursor: int, _timeout: float) -> SimpleNamespace:
        if not self._read:
            self._read = True
            return SimpleNamespace(data=b"bash-5.2$ ", next_cursor=10)
        return SimpleNamespace(data=b"", next_cursor=10)

    def write(self, data: bytes) -> None:
        self.writes.append(data)


class FakeDisconnectingTerminal(FakeReadyTerminal):
    def write(self, data: bytes) -> None:
        super().write(data)
        if b"__SERVEROPS_BEGIN_" in data:
            self.running = False


class SpikeSecretCleanupTests(unittest.TestCase):
    def test_spike_ssh_arguments_have_an_explicit_host_boundary(self) -> None:
        arguments = cli._ssh_arguments(
            Path("ssh.exe"),
            2222,
            Path("known_hosts"),
        )

        boundary = arguments.index("--")
        self.assertEqual(arguments[boundary + 1], "127.0.0.1")
        self.assertEqual(arguments[boundary + 2 :], ["bash", "--noprofile", "--norc", "-i"])

    def test_legacy_spike_disables_all_shell_prompts_before_framing(self) -> None:
        with patch.object(spike_session, "ConPtyProcess", FakeReadyTerminal):
            session = spike_session.SshSpikeSession()
            session.open(["ssh.exe"], lambda _kind, _prompt: "", timeout=1)

        initialization = b"".join(session.terminal.writes)
        self.assertIn(b"builtin readonly", initialization)
        for prompt in (b"PS1=''", b"PS2=''", b"PS3=''", b"PS4=''"):
            self.assertIn(prompt, initialization)

    def test_legacy_spike_maps_disconnect_after_delivery_to_outcome_unknown(self) -> None:
        with patch.object(spike_session, "ConPtyProcess", FakeDisconnectingTerminal):
            session = spike_session.SshSpikeSession()
            session.open(["ssh.exe"], lambda _kind, _prompt: "", timeout=1)

            with self.assertRaises(spike_session.OutcomeUnknown):
                session.execute("remote-change", lambda _kind, _prompt: "", timeout=1)

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
