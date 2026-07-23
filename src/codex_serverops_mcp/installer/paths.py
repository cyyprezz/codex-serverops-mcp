from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from codex_serverops_mcp.bootstrap import LocalStatePaths

from .errors import InstallerError


@dataclass(frozen=True, slots=True)
class InstallPaths:
    app_dir: Path
    config_file: Path
    runtime_dir: Path
    audit_dir: Path
    codex_config_file: Path

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> InstallPaths:
        env = os.environ if environment is None else environment
        local_app_data = env.get("LOCALAPPDATA")
        user_profile = env.get("USERPROFILE") or env.get("HOME")
        if not local_app_data or not user_profile:
            raise InstallerError("LOCALAPPDATA and USERPROFILE are required on Windows")
        app_dir = Path(local_app_data) / "codex-serverops-mcp"
        codex_home = Path(env.get("CODEX_HOME", str(Path(user_profile) / ".codex")))
        return cls(
            app_dir=app_dir,
            config_file=app_dir / "config.toml",
            runtime_dir=app_dir / "runtime",
            audit_dir=app_dir / "audit",
            codex_config_file=codex_home / "config.toml",
        )

    def local_state_paths(self) -> LocalStatePaths:
        return LocalStatePaths.from_app_dir(self.app_dir, runtime_dir=self.runtime_dir)
