from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from codex_serverops_mcp.config import ConnectionType, ServerProfile
from codex_serverops_mcp.errors import ConfigurationError

MAX_SSH_CONFIG_OUTPUT_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class ResolvedSshTarget:
    host: str
    port: int
    user: str

    def __post_init__(self) -> None:
        for field_name, value in (("host", self.host), ("user", self.user)):
            if (
                not value
                or value != value.strip()
                or len(value) > 255
                or any(ord(character) < 32 for character in value)
            ):
                raise ConfigurationError(f"resolved SSH {field_name} is invalid")
        if isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ConfigurationError("resolved SSH port is invalid")


SshConfigRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def find_windows_ssh() -> Path:
    executable = shutil.which("ssh.exe")
    if executable is None:
        raise ConfigurationError("Windows OpenSSH client ssh.exe was not found")
    return Path(executable).resolve()


def resolve_ssh_target(
    profile: ServerProfile,
    ssh_executable: Path,
    *,
    runner: SshConfigRunner | None = None,
) -> ResolvedSshTarget:
    if profile.connection_type is ConnectionType.DIRECT:
        assert profile.host is not None
        assert profile.port is not None
        assert profile.user is not None
        return ResolvedSshTarget(profile.host, profile.port, profile.user)
    assert profile.ssh_host is not None
    completed = (runner or _run_ssh_config)(
        (str(ssh_executable), "-G", "--", profile.ssh_host)
    )
    if completed.returncode != 0:
        raise ConfigurationError("OpenSSH could not resolve the configured SSH alias")
    if len(completed.stdout.encode("utf-8")) > MAX_SSH_CONFIG_OUTPUT_BYTES:
        raise ConfigurationError("OpenSSH alias resolution output exceeded its size limit")
    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition(" ")
        if separator and key in {"hostname", "port", "user"} and key not in values:
            values[key] = value.strip()
    if set(values) != {"hostname", "port", "user"}:
        raise ConfigurationError("OpenSSH alias resolution omitted host, port or user")
    try:
        port = int(values["port"])
    except ValueError as error:
        raise ConfigurationError("OpenSSH alias resolved to an invalid port") from error
    return ResolvedSshTarget(values["hostname"], port, values["user"])


def _run_ssh_config(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        return subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=creationflags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConfigurationError("OpenSSH alias resolution failed") from error
