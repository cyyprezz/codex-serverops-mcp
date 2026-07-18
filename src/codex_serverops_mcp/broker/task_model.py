from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from codex_serverops_mcp import PACKAGE_VERSION
from codex_serverops_mcp.ipc.security import current_user_sid_string

MANAGED_TASK_MARKER = "codex-serverops-mcp:broker-task:v1"


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
        digest = hashlib.sha256(
            f"{self.executable}\0{self.argument_line}".encode()
        ).hexdigest()[:16]
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
