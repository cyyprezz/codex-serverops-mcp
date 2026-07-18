from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from codex_serverops_mcp.errors import ConfigConflictError, ConfigurationError

from .codec import decode_config, encode_config
from .locking import InterProcessFileLock
from .model import ServerOpsConfig, ServerProfile, validate_profile_name


def default_config_path(local_app_data: str | None = None) -> Path:
    root = local_app_data if local_app_data is not None else os.environ.get("LOCALAPPDATA")
    if not root:
        raise ConfigurationError("LOCALAPPDATA is unavailable")
    return Path(root) / "codex-serverops-mcp" / "config.toml"


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    config: ServerOpsConfig
    content_hash: str


class TomlProfileRepository:
    def __init__(self, path: Path | None = None, *, lock_timeout: float = 5.0) -> None:
        self.path = (path or default_config_path()).resolve()
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.lock_timeout = lock_timeout

    def load(self) -> ConfigSnapshot:
        with self._lock():
            return self._load_unlocked()[0]

    def migrate(self) -> tuple[ConfigSnapshot, bool]:
        with self._lock():
            snapshot, migrated = self._load_unlocked()
            if not migrated:
                return snapshot, False
            return self._write_unlocked(snapshot.config), True

    def save(
        self,
        config: ServerOpsConfig,
        *,
        expected_hash: str | None = None,
    ) -> ConfigSnapshot:
        with self._lock():
            current, _ = self._load_unlocked()
            self._check_hash(current.content_hash, expected_hash)
            return self._write_unlocked(config)

    def update(
        self,
        operation: Callable[[ServerOpsConfig], ServerOpsConfig],
        *,
        expected_hash: str | None = None,
    ) -> ConfigSnapshot:
        with self._lock():
            current, _ = self._load_unlocked()
            self._check_hash(current.content_hash, expected_hash)
            return self._write_unlocked(operation(current.config))

    def put_profile(
        self,
        name: str,
        profile: ServerProfile,
        *,
        expected_hash: str | None = None,
    ) -> ConfigSnapshot:
        validate_profile_name(name)
        return self.update(
            lambda config: config.with_profile(name, profile),
            expected_hash=expected_hash,
        )

    def remove_profile(
        self,
        name: str,
        *,
        expected_hash: str | None = None,
    ) -> ConfigSnapshot:
        validate_profile_name(name)
        return self.update(
            lambda config: config.without_profile(name),
            expected_hash=expected_hash,
        )

    def _lock(self) -> InterProcessFileLock:
        return InterProcessFileLock(self.lock_path, timeout=self.lock_timeout)

    def _load_unlocked(self) -> tuple[ConfigSnapshot, bool]:
        if not self.path.exists():
            content = b""
            return ConfigSnapshot(ServerOpsConfig.empty(), _content_hash(content)), False
        content = self.path.read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ConfigurationError("configuration must be UTF-8") from error
        config, migrated = decode_config(text)
        return ConfigSnapshot(config, _content_hash(content)), migrated

    def _write_unlocked(self, config: ServerOpsConfig) -> ConfigSnapshot:
        content = encode_config(config).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _secure_for_current_user(self.path.parent, directory=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            _secure_for_current_user(temporary, directory=False)
            os.replace(temporary, self.path)
            _secure_for_current_user(self.path, directory=False)
            self._sync_directory()
        finally:
            temporary.unlink(missing_ok=True)
        return ConfigSnapshot(config, _content_hash(content))

    def _sync_directory(self) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _check_hash(current_hash: str, expected_hash: str | None) -> None:
        if expected_hash is not None and expected_hash != current_hash:
            raise ConfigConflictError(
                "configuration changed after it was read; reload before writing"
            )


def _secure_for_current_user(path: Path, *, directory: bool) -> None:
    if os.name != "nt":  # pragma: no cover - product configuration is Windows-first
        return
    from codex_serverops_mcp.ipc.security import secure_path_for_current_user

    secure_path_for_current_user(str(path), directory=directory)
