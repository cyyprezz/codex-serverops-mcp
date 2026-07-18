from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from codex_serverops_mcp.config import ElevationMode, ServerProfile
from codex_serverops_mcp.errors import ServerOpsError
from codex_serverops_mcp.ssh.prompts import operation_sudo_prompt

from .errors import ElevationError
from .shell import ElevatedShellCommand, build_elevated_shell_command

MAX_ELEVATED_COMMAND_BYTES = 131_072
INTERACTIVE_ACQUIRE_TIMEOUT_SECONDS = 5.0
CommandRunner = Callable[[str, float | None, str | None], dict[str, object]]


@dataclass(slots=True)
class ElevationService:
    profile: ServerProfile
    ssh_user: str
    command_runner: CommandRunner

    def handle(self, action: str, payload: Mapping[str, object]) -> dict[str, object]:
        if action == "status":
            self._fields(payload, set())
            return self._status()
        self._require_enabled()
        if action == "acquire":
            self._fields(payload, set())
            return self._acquire()
        if action == "release":
            self._fields(payload, set())
            return self._release()
        if action == "exec":
            self._fields(payload, {"command"}, optional={"timeout"})
            return self._exec(self._command(payload), self._timeout(payload))
        raise ValueError(f"unsupported worker elevation action: {action}")

    def _status(self) -> dict[str, object]:
        if self.profile.elevation_mode is ElevationMode.DISABLED:
            return self._summary("disabled", active=False)
        result = self._run(
            "/usr/bin/sudo -n -v",
            min(10, self.profile.command_timeout_seconds),
        )
        active = self._exit_code(result) == 0
        return self._summary("active" if active else "inactive", active=active)

    def _acquire(self) -> dict[str, object]:
        non_interactive = self.profile.elevation_mode is ElevationMode.NON_INTERACTIVE
        token = None if non_interactive else secrets.token_hex(16)
        command = "/usr/bin/sudo -n -v"
        if token is not None:
            command = f"/usr/bin/sudo -p '{operation_sudo_prompt('elevation', token)}' -v"
        timeout = self.profile.command_timeout_seconds
        if token is not None:
            timeout = min(timeout, INTERACTIVE_ACQUIRE_TIMEOUT_SECONDS)
        try:
            result = self._run(command, timeout, token)
        except ServerOpsError as error:
            if error.code != "command_timed_out" or not self._cache_is_active():
                raise
            return self._summary("acquired", active=True)
        if self._exit_code(result) != 0:
            code = "elevation_authentication_required" if non_interactive else "elevation_failed"
            raise ElevationError(code, "sudo elevation could not be acquired")
        return self._summary("acquired", active=True)

    def _cache_is_active(self) -> bool:
        try:
            result = self._run(
                "/usr/bin/sudo -n -v",
                min(10, self.profile.command_timeout_seconds),
            )
            return self._exit_code(result) == 0
        except ServerOpsError:
            return False

    def _release(self) -> dict[str, object]:
        result = self._run(
            "/usr/bin/sudo -k",
            min(10, self.profile.command_timeout_seconds),
        )
        if self._exit_code(result) != 0:
            raise ElevationError(
                "elevation_release_failed",
                "sudo credentials could not be released",
            )
        return self._summary("released", active=False)

    def _exec(self, command: str, timeout: float | None) -> dict[str, object]:
        token = (
            None
            if self.profile.elevation_mode is ElevationMode.NON_INTERACTIVE
            else secrets.token_hex(16)
        )
        built = build_elevated_shell_command(
            command,
            non_interactive=self.profile.elevation_mode is ElevationMode.NON_INTERACTIVE,
            sudo_prompt_token=token,
        )
        result = self._run(
            built.command,
            self.profile.command_timeout_seconds if timeout is None else timeout,
            token,
        )
        output, elevated_exit = self._parse_elevated_output(result, built)
        if self._exit_code(result) != elevated_exit:
            raise ElevationError(
                "elevation_protocol_error",
                "elevated exit status was inconsistent",
            )
        return {
            "status": "completed",
            "exit_code": elevated_exit,
            "output": output,
            "truncated": result.get("truncated") is True,
            "duration_ms": self._duration(result),
            "elevated": True,
            "effective_user": "root",
        }

    def _parse_elevated_output(
        self,
        result: Mapping[str, object],
        built: ElevatedShellCommand,
    ) -> tuple[str, int]:
        output = result.get("output")
        if not isinstance(output, str):
            raise ElevationError("elevation_protocol_error", "sudo returned no framed output")
        end_pattern = re.compile(
            rf"(?:^|\n){re.escape(built.end_marker)}:(-?\d+)\n*$"
        )
        match = end_pattern.search(output)
        if match is None:
            code = (
                "elevation_authentication_required"
                if self.profile.elevation_mode is ElevationMode.NON_INTERACTIVE
                else "elevation_failed"
            )
            raise ElevationError(code, "sudo did not start the elevated command")
        user_output = output[: match.start()]
        begin_line = f"{built.begin_marker}\n"
        begin_index = user_output.find(begin_line)
        if begin_index >= 0:
            user_output = user_output[begin_index + len(begin_line) :]
        return user_output, int(match.group(1))

    def _run(
        self,
        command: str,
        timeout: float,
        sudo_prompt_token: str | None = None,
    ) -> dict[str, object]:
        result = self.command_runner(command, timeout, sudo_prompt_token)
        if result.get("status") != "completed":
            raise ElevationError(
                "elevation_outcome_unknown",
                "sudo outcome could not be verified",
            )
        return result

    def _summary(self, status: str, *, active: bool) -> dict[str, object]:
        return {
            "status": status,
            "active": active,
            "elevation_mode": self.profile.elevation_mode.value,
            "elevated": False,
            "effective_user": self.ssh_user,
        }

    def _require_enabled(self) -> None:
        if self.profile.elevation_mode is ElevationMode.DISABLED:
            raise ElevationError(
                "elevation_disabled",
                "guided elevation is disabled for this profile",
            )

    @staticmethod
    def _exit_code(result: Mapping[str, object]) -> int:
        exit_code = result.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise ElevationError(
                "elevation_protocol_error",
                "sudo returned no valid exit code",
            )
        return exit_code

    @staticmethod
    def _duration(result: Mapping[str, object]) -> int:
        duration = result.get("duration_ms")
        return duration if isinstance(duration, int) and not isinstance(duration, bool) else 0

    @staticmethod
    def _command(payload: Mapping[str, object]) -> str:
        command = payload["command"]
        if not isinstance(command, str) or not command or "\0" in command:
            raise ValueError("command must be non-empty text without NUL")
        if len(command.encode("utf-8")) > MAX_ELEVATED_COMMAND_BYTES:
            raise ValueError("command exceeds the 131072-byte elevation limit")
        return command

    @staticmethod
    def _timeout(payload: Mapping[str, object]) -> float | None:
        timeout = payload.get("timeout")
        if timeout is None:
            return None
        if isinstance(timeout, bool) or not isinstance(timeout, int | float):
            raise ValueError("timeout must be a number")
        result = float(timeout)
        if not 0.1 <= result <= 3_600:
            raise ValueError("timeout is outside the supported range")
        return result

    @staticmethod
    def _fields(
        payload: Mapping[str, object],
        required: set[str],
        *,
        optional: set[str] = frozenset(),
    ) -> None:
        fields = set(payload)
        if not required.issubset(fields) or not fields.issubset(required | optional):
            raise ValueError("elevation fields do not match the action")
