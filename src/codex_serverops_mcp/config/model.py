from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType

from codex_serverops_mcp import CONFIG_SCHEMA_VERSION
from codex_serverops_mcp.errors import ConfigurationError

PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REMOTE_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


class ConnectionType(StrEnum):
    SSH_CONFIG = "ssh_config"
    DIRECT = "direct"


class Authentication(StrEnum):
    OPENSSH = "openssh"
    INTERACTIVE_PASSWORD = "interactive_password"


class ElevationMode(StrEnum):
    DISABLED = "disabled"
    NON_INTERACTIVE = "non_interactive"
    INTERACTIVE = "interactive"


def validate_profile_name(name: str) -> None:
    if not PROFILE_NAME.fullmatch(name):
        raise ConfigurationError(
            "profile name must be 1-64 characters using letters, digits, '.', '_' or '-'"
        )


def _validate_display_text(value: str, field_name: str, *, maximum: int = 255) -> None:
    if not value or value != value.strip() or len(value) > maximum:
        raise ConfigurationError(f"{field_name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ConfigurationError(f"{field_name} contains a control character")


def _validate_target(value: str, field_name: str) -> None:
    _validate_display_text(value, field_name)
    if value.startswith("-") or any(character.isspace() for character in value):
        raise ConfigurationError(f"{field_name} is not a valid OpenSSH target value")


def _normalize_allowed_roots(roots: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in roots:
        if (
            not isinstance(value, str)
            or len(value.encode("utf-8")) > 4_096
            or any(ord(character) < 32 for character in value)
        ):
            raise ConfigurationError("allowed_roots must contain only text paths")
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts:
            raise ConfigurationError(f"allowed root must be an absolute normalized path: {value!r}")
        canonical = str(path)
        if canonical != value.rstrip("/") and not (canonical == "/" and value == "/"):
            raise ConfigurationError(f"allowed root must already be normalized: {value!r}")
        if canonical not in normalized:
            normalized.append(canonical)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class ServerProfile:
    display_name: str
    connection_type: ConnectionType
    authentication: Authentication
    ssh_host: str | None = None
    host: str | None = None
    port: int | None = None
    user: str | None = None
    identity_file: str | None = None
    allowed_roots: tuple[str, ...] = ()
    allow_terminal: bool = True
    allow_file_read: bool = False
    allow_file_write: bool = False
    elevation_mode: ElevationMode = ElevationMode.DISABLED
    allow_root_session: bool = False
    environment: str = "unspecified"
    command_timeout_seconds: int = 60
    max_output_bytes: int = 2_097_152

    def __post_init__(self) -> None:
        if not isinstance(self.connection_type, ConnectionType):
            raise ConfigurationError("connection_type must be a supported enum value")
        if not isinstance(self.authentication, Authentication):
            raise ConfigurationError("authentication must be a supported enum value")
        if not isinstance(self.elevation_mode, ElevationMode):
            raise ConfigurationError("elevation_mode must be a supported enum value")
        _validate_display_text(self.display_name, "display_name", maximum=128)
        _validate_display_text(self.environment, "environment", maximum=64)
        object.__setattr__(self, "allowed_roots", _normalize_allowed_roots(self.allowed_roots))

        if self.connection_type is ConnectionType.SSH_CONFIG:
            if self.ssh_host is None:
                raise ConfigurationError("ssh_config profiles require ssh_host")
            _validate_target(self.ssh_host, "ssh_host")
            if any(value is not None for value in (self.host, self.port, self.user)):
                raise ConfigurationError(
                    "ssh_config profiles cannot also define direct host, port or user"
                )
            if self.authentication is not Authentication.OPENSSH:
                raise ConfigurationError("ssh_config profiles must use OpenSSH authentication")
        elif self.connection_type is ConnectionType.DIRECT:
            if self.ssh_host is not None:
                raise ConfigurationError("direct profiles cannot define ssh_host")
            if self.host is None or self.user is None or self.port is None:
                raise ConfigurationError("direct profiles require host, port and user")
            _validate_target(self.host, "host")
            if not REMOTE_USER.fullmatch(self.user):
                raise ConfigurationError("user is not a supported Linux account name")
            if isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
                raise ConfigurationError("port must be between 1 and 65535")

        if self.identity_file is not None:
            _validate_display_text(self.identity_file, "identity_file", maximum=1_024)
            if self.authentication is not Authentication.OPENSSH:
                raise ConfigurationError(
                    "identity_file is only valid with OpenSSH authentication"
                )
        if self.allow_file_write and not self.allow_file_read:
            raise ConfigurationError("allow_file_write requires allow_file_read")
        if (self.allow_file_read or self.allow_file_write) and not self.allowed_roots:
            raise ConfigurationError("structured file access requires at least one allowed root")
        if self.allow_root_session and self.elevation_mode is ElevationMode.DISABLED:
            raise ConfigurationError("a root session requires an enabled elevation mode")
        if self.allow_root_session and not self.allow_terminal:
            raise ConfigurationError("a root session requires terminal access")
        if isinstance(self.command_timeout_seconds, bool) or not (
            1 <= self.command_timeout_seconds <= 3_600
        ):
            raise ConfigurationError("command_timeout_seconds must be between 1 and 3600")
        if isinstance(self.max_output_bytes, bool) or not (
            4_096 <= self.max_output_bytes <= 16_777_216
        ):
            raise ConfigurationError("max_output_bytes must be between 4096 and 16777216")


@dataclass(frozen=True, slots=True)
class ServerOpsConfig:
    profiles: Mapping[str, ServerProfile] = field(default_factory=dict)
    schema_version: int = CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONFIG_SCHEMA_VERSION:
            raise ConfigurationError(
                f"config schema must be {CONFIG_SCHEMA_VERSION}, got {self.schema_version}"
            )
        copied = dict(self.profiles)
        for name, profile in copied.items():
            validate_profile_name(name)
            if not isinstance(profile, ServerProfile):
                raise ConfigurationError(f"profile {name!r} has an invalid value")
        object.__setattr__(self, "profiles", MappingProxyType(copied))

    @classmethod
    def empty(cls) -> ServerOpsConfig:
        return cls()

    def with_profile(self, name: str, profile: ServerProfile) -> ServerOpsConfig:
        validate_profile_name(name)
        profiles = dict(self.profiles)
        profiles[name] = profile
        return ServerOpsConfig(profiles=profiles)

    def without_profile(self, name: str) -> ServerOpsConfig:
        validate_profile_name(name)
        profiles = dict(self.profiles)
        if name not in profiles:
            raise ConfigurationError(f"profile does not exist: {name}")
        del profiles[name]
        return ServerOpsConfig(profiles=profiles)
