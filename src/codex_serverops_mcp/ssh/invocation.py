from __future__ import annotations

from pathlib import Path

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerProfile,
)


def build_ssh_arguments(
    profile: ServerProfile,
    *,
    ssh_executable: Path,
    known_hosts_file: Path,
    root_session: bool = False,
    root_sudo_prompt: str | None = None,
) -> list[str]:
    """Build argv for Windows OpenSSH without constructing a shell command."""
    arguments = [
        str(ssh_executable),
        "-tt",
        "-o",
        "BatchMode=no",
        "-o",
        "ControlMaster=no",
        "-o",
        "StrictHostKeyChecking=ask",
        "-o",
        f"UserKnownHostsFile={known_hosts_file}",
        "-o",
        "NumberOfPasswordPrompts=1",
    ]

    if profile.connection_type is ConnectionType.DIRECT:
        assert profile.host is not None
        assert profile.port is not None
        assert profile.user is not None
        arguments.extend(("-p", str(profile.port), "-l", profile.user))
        if profile.authentication is Authentication.INTERACTIVE_PASSWORD:
            arguments.extend(
                (
                    "-o",
                    "PreferredAuthentications=keyboard-interactive,password",
                    "-o",
                    "PubkeyAuthentication=no",
                )
            )
        else:
            arguments.extend(
                (
                    "-o",
                    "PreferredAuthentications=publickey",
                    "-o",
                    "PasswordAuthentication=no",
                    "-o",
                    "KbdInteractiveAuthentication=no",
                )
            )
        if profile.identity_file is not None:
            arguments.extend(("-i", profile.identity_file, "-o", "IdentitiesOnly=yes"))
        target = profile.host
    else:
        assert profile.ssh_host is not None
        if profile.identity_file is not None:
            arguments.extend(("-i", profile.identity_file, "-o", "IdentitiesOnly=yes"))
        target = profile.ssh_host

    remote_command = ["/bin/bash", "--noprofile", "--norc", "-i"]
    if root_session:
        if (
            profile.elevation_mode is ElevationMode.INTERACTIVE
            and not root_sudo_prompt
        ):
            raise ValueError("interactive root sessions require an operation-bound sudo prompt")
        non_interactive = (
            ["-n"] if profile.elevation_mode is ElevationMode.NON_INTERACTIVE else []
        )
        prompt = (
            []
            if profile.elevation_mode is ElevationMode.NON_INTERACTIVE
            else ["-p", root_sudo_prompt]
        )
        remote_command = [
            "/usr/bin/sudo",
            *non_interactive,
            *prompt,
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
            *remote_command,
        ]
    arguments.extend(("--", target, *remote_command))
    return arguments
