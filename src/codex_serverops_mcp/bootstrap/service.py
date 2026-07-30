from __future__ import annotations

import json
import os
import stat
import uuid
from pathlib import Path

from codex_serverops_mcp.config import TomlProfileRepository
from codex_serverops_mcp.config.locking import InterProcessFileLock
from codex_serverops_mcp.errors import ConfigurationError

from .model import BOOTSTRAP_SCHEMA_VERSION, BootstrapReport, LocalStatePaths


class LocalStateBootstrapper:
    def __init__(
        self,
        paths: LocalStatePaths,
        *,
        lock_timeout: float = 5.0,
    ) -> None:
        self.paths = paths
        self.lock_timeout = lock_timeout

    def ensure(self) -> BootstrapReport:
        self._ensure_directory(self.paths.app_dir)
        self._reject_reparse_or_wrong_type(self.paths.bootstrap_lock, directory=False)
        with InterProcessFileLock(self.paths.bootstrap_lock, timeout=self.lock_timeout):
            self._secure(self.paths.bootstrap_lock, directory=False)
            for path in (
                self.paths.runtime_dir,
                self.paths.runtime_dir / "workers",
                self.paths.runtime_dir / "setup",
                self.paths.audit_dir,
                self.paths.migrations_dir,
            ):
                self._ensure_directory(path)
            self._reject_reparse_or_wrong_type(self.paths.config_file, directory=False)
            config_lock = self.paths.config_file.with_name(
                f"{self.paths.config_file.name}.lock"
            )
            self._ensure_lock_file(config_lock)
            preparation = TomlProfileRepository(
                self.paths.config_file,
                lock_timeout=self.lock_timeout,
            ).initialize_or_migrate(migration_backup_dir=self.paths.migrations_dir)
            self._secure(self.paths.config_file, directory=False)
            self._ensure_lock_file(self.paths.audit_dir / ".audit.lock")
            self._ensure_state()
        return BootstrapReport(
            app_dir=self.paths.app_dir,
            config_created=preparation.created,
            config_migrated=preparation.migrated,
            migration_backup=preparation.backup_path,
            state_schema_version=BOOTSTRAP_SCHEMA_VERSION,
        )

    def _ensure_state(self) -> None:
        path = self.paths.state_file
        self._reject_reparse_or_wrong_type(path, directory=False)
        if path.exists():
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ConfigurationError("bootstrap state is invalid") from error
            if document != {"schema_version": BOOTSTRAP_SCHEMA_VERSION}:
                raise ConfigurationError("bootstrap state has an unsupported schema")
            self._secure(path, directory=False)
            return
        content = (
            json.dumps({"schema_version": BOOTSTRAP_SCHEMA_VERSION}, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        self._atomic_write(path, content)

    def _ensure_lock_file(self, path: Path) -> None:
        self._reject_reparse_or_wrong_type(path, directory=False)
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        self._secure(path, directory=False)

    def _ensure_directory(self, path: Path) -> None:
        self._reject_reparse_or_wrong_type(path, directory=True)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._secure(path, directory=True)

    @staticmethod
    def _reject_reparse_or_wrong_type(path: Path, *, directory: bool) -> None:
        if not path.exists() and not path.is_symlink():
            return
        try:
            details = path.stat(follow_symlinks=False)
        except OSError as error:
            raise ConfigurationError(f"managed local path cannot be inspected: {path}") from error
        attributes = getattr(details, "st_file_attributes", 0)
        if path.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ConfigurationError(f"managed local path must not be a reparse point: {path}")
        matches = stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(details.st_mode)
        if not matches:
            expected = "directory" if directory else "file"
            raise ConfigurationError(f"managed local path must be a {expected}: {path}")

    def _atomic_write(self, path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._secure(temporary, directory=False)
            os.replace(temporary, path)
            self._secure(path, directory=False)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _secure(path: Path, *, directory: bool) -> None:
        if os.name == "nt":
            from codex_serverops_mcp.ipc.security import secure_path_for_current_user

            secure_path_for_current_user(str(path), directory=directory)
        else:  # pragma: no cover - production target is Windows
            path.chmod(0o700 if directory else 0o600)


def ensure_local_state(paths: LocalStatePaths | None = None) -> BootstrapReport:
    return LocalStateBootstrapper(paths or LocalStatePaths.from_environment()).ensure()
