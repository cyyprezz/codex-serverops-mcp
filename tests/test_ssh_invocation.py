from __future__ import annotations

import unittest
from pathlib import Path

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerProfile,
)
from codex_serverops_mcp.ssh.invocation import build_ssh_arguments


class SshInvocationTests(unittest.TestCase):
    def test_direct_target_is_built_as_separate_arguments(self) -> None:
        profile = ServerProfile(
            display_name="Direct",
            connection_type=ConnectionType.DIRECT,
            authentication=Authentication.INTERACTIVE_PASSWORD,
            host="192.0.2.10",
            port=2222,
            user="deploy",
        )

        arguments = build_ssh_arguments(
            profile,
            ssh_executable=Path("C:/Windows/System32/OpenSSH/ssh.exe"),
            known_hosts_file=Path("C:/state/known_hosts"),
        )

        self.assertEqual(arguments[0], "C:\\Windows\\System32\\OpenSSH\\ssh.exe")
        self.assertIn("2222", arguments)
        self.assertIn("deploy", arguments)
        self.assertEqual(
            arguments[-6:],
            ["--", "192.0.2.10", "/bin/bash", "--noprofile", "--norc", "-i"],
        )
        self.assertNotIn("192.0.2.10 deploy", arguments)

    def test_ssh_alias_does_not_invent_direct_target_fields(self) -> None:
        profile = ServerProfile(
            display_name="Alias",
            connection_type=ConnectionType.SSH_CONFIG,
            authentication=Authentication.OPENSSH,
            ssh_host="corp-prod",
        )

        arguments = build_ssh_arguments(
            profile,
            ssh_executable=Path("ssh.exe"),
            known_hosts_file=Path("known_hosts"),
        )

        self.assertNotIn("-l", arguments)
        self.assertNotIn("-p", arguments)
        self.assertEqual(
            arguments[-6:],
            ["--", "corp-prod", "/bin/bash", "--noprofile", "--norc", "-i"],
        )

    def test_root_session_is_a_separate_non_interactive_sudo_login_bash(self) -> None:
        profile = ServerProfile(
            display_name="Root",
            connection_type=ConnectionType.DIRECT,
            authentication=Authentication.OPENSSH,
            host="192.0.2.10",
            port=22,
            user="deploy",
            elevation_mode=ElevationMode.NON_INTERACTIVE,
            allow_root_session=True,
        )

        arguments = build_ssh_arguments(
            profile,
            ssh_executable=Path("ssh.exe"),
            known_hosts_file=Path("known_hosts"),
            root_session=True,
        )

        expected = [
                "--",
                "192.0.2.10",
                "/usr/bin/sudo",
                "-n",
                "-i",
                "--",
                "/usr/bin/env",
                "-u",
                "BASH_ENV",
                "-u",
                "ENV",
                "-u",
                "SHELLOPTS",
                "-u",
                "BASHOPTS",
                "/bin/bash",
                "--noprofile",
                "--norc",
                "-i",
        ]
        self.assertEqual(arguments[-len(expected) :], expected)

    def test_interactive_root_session_requires_operation_bound_sudo_prompt(self) -> None:
        profile = ServerProfile(
            display_name="Root",
            connection_type=ConnectionType.DIRECT,
            authentication=Authentication.OPENSSH,
            host="192.0.2.10",
            port=22,
            user="deploy",
            elevation_mode=ElevationMode.INTERACTIVE,
            allow_root_session=True,
        )

        with self.assertRaisesRegex(ValueError, "operation-bound sudo prompt"):
            build_ssh_arguments(
                profile,
                ssh_executable=Path("ssh.exe"),
                known_hosts_file=Path("known_hosts"),
                root_session=True,
            )

        prompt = "[sudo] password for %u: serverops-root-operation-token"
        arguments = build_ssh_arguments(
            profile,
            ssh_executable=Path("ssh.exe"),
            known_hosts_file=Path("known_hosts"),
            root_session=True,
            root_sudo_prompt=prompt,
        )

        self.assertIn("-p", arguments)
        self.assertIn(prompt, arguments)


if __name__ == "__main__":
    unittest.main()
