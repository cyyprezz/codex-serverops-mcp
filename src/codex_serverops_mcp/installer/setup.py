from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from codex_serverops_mcp.bootstrap import LocalStateBootstrapper

from .errors import InstallerError
from .paths import InstallPaths


def prepare_local_install(paths: InstallPaths) -> dict[str, object]:
    report = LocalStateBootstrapper(paths.local_state_paths()).ensure()
    return {
        "status": "prepared",
        "config_file": str(paths.config_file),
        "codex_config_file": str(paths.codex_config_file),
        "config_migrated": report.config_migrated,
        "config_created": report.config_created,
        "migration_backup": (
            None if report.migration_backup is None else str(report.migration_backup)
        ),
    }


def remove_local_data(paths: InstallPaths) -> None:
    target = Path(os.path.abspath(paths.app_dir))
    if (
        target.name != "codex-serverops-mcp"
        or target == Path(target.anchor)
        or target.parent == Path(target.anchor)
    ):
        raise InstallerError("refusing to remove an unexpected application data path")
    if not target.exists() and not target.is_symlink():
        return
    try:
        details = target.stat(follow_symlinks=False)
    except OSError as error:
        raise InstallerError("the local application data path could not be inspected") from error
    attributes = getattr(details, "st_file_attributes", 0)
    if target.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise InstallerError("refusing to remove a reparse-point application data path")
    if not stat.S_ISDIR(details.st_mode):
        raise InstallerError("the local application data path is not a directory")
    shutil.rmtree(target)
