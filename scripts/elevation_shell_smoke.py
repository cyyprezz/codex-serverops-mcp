from __future__ import annotations

import json
import subprocess
from contextlib import suppress

from codex_serverops_mcp.elevation.shell import build_elevated_shell_command

CONTAINER_NAME = "codex-serverops-elevation-shell-smoke"
IMAGE_NAME = "codex-serverops-spike:local"


def _run(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def run() -> dict[str, object]:
    _run(["docker", "rm", "-f", CONTAINER_NAME], check=False)
    _run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            CONTAINER_NAME,
            "--entrypoint",
            "sleep",
            IMAGE_NAME,
            "infinity",
        ]
    )
    try:
        denied = build_elevated_shell_command("id -u", non_interactive=True)
        denied_result = _run(
            [
                "docker",
                "exec",
                "--user",
                "serverops",
                CONTAINER_NAME,
                "bash",
                "--noprofile",
                "--norc",
                "-c",
                denied.command,
            ],
            check=False,
        )
        if denied_result.returncode == 0 or denied.end_marker in denied_result.stdout:
            raise AssertionError("sudo -n did not fail closed before NOPASSWD configuration")
        _run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "printf 'serverops ALL=(ALL:ALL) NOPASSWD: ALL\\n' "
                "> /etc/sudoers.d/serverops; chmod 0440 /etc/sudoers.d/serverops",
            ]
        )
        built = build_elevated_shell_command(
            "printf 'elevated-user='; id -u; exit 7",
            non_interactive=True,
        )
        completed = _run(
            [
                "docker",
                "exec",
                "--user",
                "serverops",
                CONTAINER_NAME,
                "bash",
                "--noprofile",
                "--norc",
                "-c",
                built.command,
            ],
            check=False,
        )
        output = completed.stdout + completed.stderr
        if (
            completed.returncode != 7
            or built.begin_marker not in output
            or f"{built.end_marker}:7" not in output
            or "elevated-user=0" not in output
        ):
            raise AssertionError(f"unexpected elevated shell result: {output!r}")
        return {
            "status": "passed",
            "checks": ["sudo_n_failure", "root_marker", "root_uid", "exit_code"],
        }
    finally:
        with suppress(Exception):
            _run(["docker", "rm", "-f", CONTAINER_NAME], check=False)


def main() -> None:
    print(json.dumps(run(), sort_keys=True))


if __name__ == "__main__":
    main()
