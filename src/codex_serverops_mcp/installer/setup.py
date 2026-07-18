from __future__ import annotations

import os
import shutil
from pathlib import Path

from codex_serverops_mcp.config import ServerOpsConfig, TomlProfileRepository
from codex_serverops_mcp.runtime import RuntimeDirectory

from .errors import InstallerError
from .paths import InstallPaths


def prepare_local_install(paths: InstallPaths) -> dict[str, object]:
    paths.app_dir.mkdir(parents=True, exist_ok=True)
    _secure(paths.app_dir, directory=True)
    repository = TomlProfileRepository(paths.config_file)
    if paths.config_file.exists():
        _snapshot, migrated = repository.migrate()
    else:
        repository.save(ServerOpsConfig.empty())
        migrated = False
    _secure(paths.config_file, directory=False)
    if repository.lock_path.exists():
        _secure(repository.lock_path, directory=False)
    RuntimeDirectory(paths.runtime_dir).prepare()
    paths.audit_dir.mkdir(parents=True, exist_ok=True)
    _secure(paths.audit_dir, directory=True)
    return {
        "status": "prepared",
        "config_file": str(paths.config_file),
        "codex_config_file": str(paths.codex_config_file),
        "config_migrated": migrated,
    }


def remove_local_data(paths: InstallPaths) -> None:
    target = paths.app_dir.resolve()
    if target.name != "codex-serverops-mcp" or target == Path(target.anchor):
        raise InstallerError("refusing to remove an unexpected application data path")
    if target.exists():
        shutil.rmtree(target)


def _secure(path: Path, *, directory: bool) -> None:
    if os.name != "nt":  # pragma: no cover - installer target is Windows
        return
    from codex_serverops_mcp.ipc.security import secure_path_for_current_user

    secure_path_for_current_user(str(path), directory=directory)
