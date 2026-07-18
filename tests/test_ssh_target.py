from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from codex_serverops_mcp.config import Authentication, ConnectionType, ServerProfile
from codex_serverops_mcp.errors import ConfigurationError
from codex_serverops_mcp.ssh.target import ResolvedSshTarget, resolve_ssh_target


class SshTargetResolutionTests(unittest.TestCase):
    def test_direct_profile_does_not_invoke_ssh_config_resolution(self) -> None:
        profile = ServerProfile(
            display_name="Direct",
            connection_type=ConnectionType.DIRECT,
            authentication=Authentication.OPENSSH,
            host="192.0.2.10",
            port=2222,
            user="deploy",
        )

        target = resolve_ssh_target(
            profile,
            Path("ssh.exe"),
            runner=lambda _arguments: self.fail("runner must not be called"),
        )

        self.assertEqual(target, ResolvedSshTarget("192.0.2.10", 2222, "deploy"))

    def test_alias_uses_openssh_resolved_host_port_and_user(self) -> None:
        profile = ServerProfile(
            display_name="Alias",
            connection_type=ConnectionType.SSH_CONFIG,
            authentication=Authentication.OPENSSH,
            ssh_host="customer-prod",
        )
        calls: list[tuple[str, ...]] = []

        def run(arguments):
            calls.append(tuple(arguments))
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout="host customer-prod\nhostname 203.0.113.9\nuser release\nport 2200\n",
                stderr="",
            )

        target = resolve_ssh_target(profile, Path("C:/OpenSSH/ssh.exe"), runner=run)

        self.assertEqual(target, ResolvedSshTarget("203.0.113.9", 2200, "release"))
        self.assertEqual(
            calls,
            [(str(Path("C:/OpenSSH/ssh.exe")), "-G", "--", "customer-prod")],
        )

    def test_alias_resolution_fails_closed_on_missing_required_fields(self) -> None:
        profile = ServerProfile(
            display_name="Alias",
            connection_type=ConnectionType.SSH_CONFIG,
            authentication=Authentication.OPENSSH,
            ssh_host="broken-alias",
        )

        with self.assertRaises(ConfigurationError):
            resolve_ssh_target(
                profile,
                Path("ssh.exe"),
                runner=lambda arguments: subprocess.CompletedProcess(
                    arguments,
                    0,
                    stdout="hostname example.test\nuser deploy\n",
                    stderr="",
                ),
            )


if __name__ == "__main__":
    unittest.main()
