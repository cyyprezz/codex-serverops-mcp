from __future__ import annotations

import unittest
from unittest.mock import patch

from codex_serverops_mcp.config import ElevationMode
from codex_serverops_mcp.installer.checks import LocalChecker
from codex_serverops_mcp.installer.doctor import REQUIRED_REMOTE_COMMANDS, Doctor


class FakeDoctorServices:
    def __init__(self, *, missing: tuple[str, ...] = (), sudo_output: str = "") -> None:
        self.missing = missing
        self.sudo_output = sudo_output
        self.commands: list[str] = []

    def server_exec(self, _session_id: str, command: str) -> dict[str, object]:
        self.commands.append(command)
        if "BASH_VERSION" in command:
            return {"status": "completed", "exit_code": 0, "output": "5.2.0"}
        if "command -v" in command:
            return {"status": "completed", "exit_code": 0, "output": "\n".join(self.missing)}
        if "realpath -e" in command:
            return {"status": "completed", "exit_code": 0, "output": "/opt/app\n"}
        if command == "sudo -n -l":
            return {
                "status": "completed",
                "exit_code": 0 if self.sudo_output else 1,
                "output": self.sudo_output,
            }
        raise AssertionError(f"unexpected command: {command}")

    def server_elevation(self, _action: str, _session_id: str) -> dict[str, object]:
        return {"status": "active", "active": True}


class DoctorChecksTests(unittest.TestCase):
    def test_claude_check_uses_only_documented_cli_discovery(self) -> None:
        with patch(
            "codex_serverops_mcp.installer.checks.shutil.which",
            return_value=r"C:\Tools\claude.exe",
        ):
            result = LocalChecker._claude_code()
        self.assertEqual(result.code, "claude_code")
        self.assertEqual(result.level.value, "pass")

    def test_remote_command_check_reports_exact_missing_tools(self) -> None:
        services = FakeDoctorServices(missing=("realpath", "sha256sum"))
        checks = Doctor._bash_and_commands(services, "sess")  # type: ignore[arg-type]
        self.assertEqual(checks[0].level.value, "pass")
        self.assertEqual(checks[1].code, "remote_commands_missing")
        self.assertIn("realpath", checks[1].message)
        self.assertIn("sha256sum", checks[1].message)
        for command in REQUIRED_REMOTE_COMMANDS:
            self.assertIn(command, services.commands[1])

    def test_allowed_root_is_encoded_not_interpolated(self) -> None:
        services = FakeDoctorServices()
        root = "/opt/app with spaces"
        checks = Doctor._allowed_roots(services, "sess", (root,))  # type: ignore[arg-type]
        self.assertEqual(checks[0].level.value, "pass")
        self.assertNotIn(root, services.commands[0])

    def test_sudo_check_warns_without_claiming_authoritative_classification(self) -> None:
        services = FakeDoctorServices(sudo_output="(ALL) NOPASSWD: ALL\n")
        checks = Doctor._sudo(  # type: ignore[arg-type]
            services,
            "sess",
            ElevationMode.NON_INTERACTIVE,
        )
        codes = {check.code for check in checks}
        self.assertIn("sudo_noninteractive_active", codes)
        self.assertIn("sudo_noninteractive_available", codes)
        self.assertIn("sudo_broad_nopasswd", codes)


if __name__ == "__main__":
    unittest.main()
