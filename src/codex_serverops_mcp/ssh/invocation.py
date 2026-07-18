from __future__ import annotations

from pathlib import Path

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerProfile,
)

from .prompts import SUDO_PROMPT_TEXT


def build_ssh_arguments(
    profile: ServerProfile,
    *,
    ssh_executable: Path,
    known_hosts_file: Path,
    root_session: bool = False,
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
        if profile.identity_file is not None:
            arguments.extend(("-i", profile.identity_file, "-o", "IdentitiesOnly=yes"))
        target = profile.host
    else:
        assert profile.ssh_host is not None
        if profile.identity_file is not None:
            arguments.extend(("-i", profile.identity_file, "-o", "IdentitiesOnly=yes"))
        target = profile.ssh_host

    remote_command = ["bash", "--noprofile", "--norc", "-i"]
    if root_session:
        non_interactive = (
            ["-n"] if profile.elevation_mode is ElevationMode.NON_INTERACTIVE else []
        )
        prompt = (
            []
            if profile.elevation_mode is ElevationMode.NON_INTERACTIVE
            else ["-p", SUDO_PROMPT_TEXT]
        )
        remote_command = ["sudo", *non_interactive, *prompt, "-i", "--", *remote_command]
    arguments.extend(("--", target, *remote_command))
    return arguments
