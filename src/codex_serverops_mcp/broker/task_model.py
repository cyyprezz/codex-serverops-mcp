from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from codex_serverops_mcp import PACKAGE_VERSION
from codex_serverops_mcp.ipc.security import current_user_sid_string

MANAGED_TASK_MARKER = "codex-serverops-mcp:broker-task:v1"
MANAGED_DESCRIPTION = re.compile(
    rf"^Codex ServerOps MCP per-user broker\. Managed marker: "
    rf"{re.escape(MANAGED_TASK_MARKER)}; source=(?P<source>[^\r\n]+); "
    r"action=(?P<action>[0-9a-f]{16})$"
)


def broker_action_digest(
    executable: str | Path,
    argument_line: str,
    working_directory: str | Path = "",
) -> str:
    action = f"{executable}\0{argument_line}\0{working_directory}"
    return hashlib.sha256(action.encode()).hexdigest()[:16]


def _legacy_broker_action_digest(executable: str, argument_line: str) -> str:
    return hashlib.sha256(f"{executable}\0{argument_line}".encode()).hexdigest()[:16]


def managed_description_matches(
    description: str,
    executable: str,
    argument_line: str,
    working_directory: str,
) -> bool:
    match = MANAGED_DESCRIPTION.fullmatch(description)
    expected_digests = {
        broker_action_digest(executable, argument_line, working_directory),
    }
    if not working_directory:
        expected_digests.add(_legacy_broker_action_digest(executable, argument_line))
    return (
        match is not None
        and bool(match.group("source").strip())
        and match.group("action") in expected_digests
    )


@dataclass(frozen=True, slots=True)
class BrokerTaskSpec:
    executable: Path
    arguments: tuple[str, ...]
    source: str
    working_directory: Path | None = None

    def validate(self) -> None:
        if not self.executable.is_absolute() or not self.executable.is_file():
            raise ValueError("broker task executable must be an existing absolute file")
        if not self.arguments or not all(self.arguments):
            raise ValueError("broker task arguments must not be empty")
        if not self.source.strip():
            raise ValueError("broker task source must not be empty")
        if self.working_directory is not None and not self.working_directory.is_absolute():
            raise ValueError("broker task working directory must be absolute")

    @property
    def argument_line(self) -> str:
        return subprocess.list2cmdline(list(self.arguments))

    @property
    def description(self) -> str:
        digest = broker_action_digest(
            self.executable,
            self.argument_line,
            self.working_directory or "",
        )
        return (
            "Codex ServerOps MCP per-user broker. "
            f"Managed marker: {MANAGED_TASK_MARKER}; source={self.source}; action={digest}"
        )


@dataclass(frozen=True, slots=True)
class BrokerTaskStatus:
    name: str
    exists: bool
    managed: bool
    running: bool
    executable: str | None = None
    arguments: str | None = None


def broker_task_name(sid: str | None = None) -> str:
    user_sid = sid or current_user_sid_string()
    digest = hashlib.sha256(user_sid.encode("ascii")).hexdigest()[:12]
    return f"Codex ServerOps MCP Broker {digest}"


def production_broker_task_spec(
    *,
    version: str = PACKAGE_VERSION,
    uvx_path: str | None = None,
) -> BrokerTaskSpec:
    executable = uvx_path or shutil.which("uvx")
    if executable is None:
        raise ValueError("uvx is required to install the per-user broker task")
    return BrokerTaskSpec(
        executable=Path(executable).resolve(),
        arguments=(
            "--from",
            f"codex-serverops-mcp=={version}",
            "serverops-broker",
        ),
        source=f"codex-serverops-mcp=={version}",
    )


def wheel_broker_task_spec(
    wheel: Path,
    *,
    uvx_path: str | None = None,
    python_path: str | None = None,
) -> BrokerTaskSpec:
    resolved_wheel = wheel.resolve()
    if not resolved_wheel.is_file() or resolved_wheel.suffix != ".whl":
        raise ValueError("development broker task requires an existing wheel")
    cache_directory = resolved_wheel.parents[1] / ".uv-cache"
    if not cache_directory.is_dir():
        raise ValueError("development broker task requires the project-local uv cache")
    executable = uvx_path or shutil.which("uvx")
    if executable is None:
        raise ValueError("uvx is required to install the development broker task")
    python = Path(python_path or sys.executable).resolve()
    if not python.is_file():
        raise ValueError("development broker task requires an existing Python runtime")
    return BrokerTaskSpec(
        executable=Path(executable).resolve(),
        arguments=(
            "--python",
            str(python),
            "--cache-dir",
            str(cache_directory),
            "--offline",
            "--from",
            str(resolved_wheel),
            "serverops-broker",
        ),
        source=f"development-wheel:{resolved_wheel.name}",
    )
