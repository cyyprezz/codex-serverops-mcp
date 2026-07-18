from __future__ import annotations

import re
import unittest

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerProfile,
)
from codex_serverops_mcp.elevation.errors import ElevationError
from codex_serverops_mcp.elevation.service import ElevationService
from codex_serverops_mcp.elevation.shell import build_elevated_shell_command

BEGIN = re.compile(r"__SERVEROPS_ELEVATED_BEGIN_[0-9a-f]{32}__")
END = re.compile(r"__SERVEROPS_ELEVATED_END_[0-9a-f]{32}__")


def profile(mode: ElevationMode) -> ServerProfile:
    return ServerProfile(
        display_name="Elevation",
        connection_type=ConnectionType.DIRECT,
        authentication=Authentication.OPENSSH,
        host="example.test",
        port=22,
        user="deploy",
        elevation_mode=mode,
        allow_root_session=mode is not ElevationMode.DISABLED,
    )


class FakeRunner:
    def __init__(self, *, exit_code: int = 0, elevated_output: str | None = None) -> None:
        self.exit_code = exit_code
        self.elevated_output = elevated_output
        self.calls: list[tuple[str, float | None]] = []

    def __call__(self, command: str, timeout: float | None) -> dict[str, object]:
        self.calls.append((command, timeout))
        output = ""
        begin = BEGIN.search(command)
        end = END.search(command)
        if self.elevated_output is not None and begin is not None and end is not None:
            output = (
                f"sudo notice\n{begin.group()}\n{self.elevated_output}\n"
                f"{end.group()}:{self.exit_code}"
            )
        return {
            "status": "completed",
            "exit_code": self.exit_code,
            "output": output,
            "truncated": False,
            "duration_ms": 12,
        }


class ElevationServiceTests(unittest.TestCase):
    def test_disabled_mode_reports_status_and_rejects_guided_actions(self) -> None:
        runner = FakeRunner()
        service = ElevationService(profile(ElevationMode.DISABLED), "deploy", runner)

        self.assertEqual(service.handle("status", {})["status"], "disabled")
        with self.assertRaises(ElevationError) as captured:
            service.handle("acquire", {})

        self.assertEqual(captured.exception.code, "elevation_disabled")
        self.assertEqual(runner.calls, [])

    def test_non_interactive_mode_never_falls_back_to_a_password_prompt(self) -> None:
        runner = FakeRunner(exit_code=1)
        service = ElevationService(profile(ElevationMode.NON_INTERACTIVE), "deploy", runner)

        with self.assertRaises(ElevationError) as captured:
            service.handle("acquire", {})

        self.assertEqual(captured.exception.code, "elevation_authentication_required")
        self.assertEqual(runner.calls[0][0], "sudo -n -v")

    def test_elevated_exec_is_encoded_framed_and_preserves_user_exit(self) -> None:
        runner = FakeRunner(exit_code=7, elevated_output="root-output\n")
        service = ElevationService(profile(ElevationMode.NON_INTERACTIVE), "deploy", runner)
        hostile = "printf '$HOME'; exit 7"

        result = service.handle("exec", {"command": hostile, "timeout": 30})

        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["output"], "root-output\n")
        self.assertEqual(result["effective_user"], "root")
        self.assertNotIn(hostile, runner.calls[0][0])
        self.assertIn("sudo -n --", runner.calls[0][0])

    def test_missing_elevated_completion_marker_fails_closed(self) -> None:
        service = ElevationService(
            profile(ElevationMode.NON_INTERACTIVE),
            "deploy",
            FakeRunner(exit_code=1),
        )

        with self.assertRaises(ElevationError) as captured:
            service.handle("exec", {"command": "id -u"})

        self.assertEqual(captured.exception.code, "elevation_authentication_required")

    def test_large_command_uses_bounded_terminal_lines(self) -> None:
        built = build_elevated_shell_command("x" * 10_000, non_interactive=False)

        self.assertLessEqual(max(map(len, built.command.splitlines())), 518)


if __name__ == "__main__":
    unittest.main()
