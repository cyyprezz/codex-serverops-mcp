from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from codex_serverops_mcp.errors import ConfigurationError

BOOTSTRAP_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class LocalStatePaths:
    app_dir: Path
    config_file: Path
    runtime_dir: Path
    audit_dir: Path
    migrations_dir: Path
    state_file: Path
    bootstrap_lock: Path

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        runtime_dir: Path | None = None,
    ) -> LocalStatePaths:
        env = os.environ if environment is None else environment
        local_app_data = env.get("LOCALAPPDATA")
        if not local_app_data:
            raise ConfigurationError("LOCALAPPDATA is unavailable")
        app_dir = Path(local_app_data) / "codex-serverops-mcp"
        return cls.from_app_dir(app_dir, runtime_dir=runtime_dir)

    @classmethod
    def from_app_dir(
        cls,
        app_dir: Path,
        *,
        runtime_dir: Path | None = None,
    ) -> LocalStatePaths:
        root = Path(os.path.abspath(app_dir))
        runtime = Path(os.path.abspath(runtime_dir or root / "runtime"))
        return cls(
            app_dir=root,
            config_file=root / "config.toml",
            runtime_dir=runtime,
            audit_dir=root / "audit",
            migrations_dir=root / "migrations",
            state_file=root / "state.json",
            bootstrap_lock=root / ".bootstrap.lock",
        )

@dataclass(frozen=True, slots=True)
class BootstrapReport:
    app_dir: Path
    config_created: bool
    config_migrated: bool
    migration_backup: Path | None
    state_schema_version: int
