from __future__ import annotations

import copy
import json
import tomllib
from collections.abc import Mapping

from codex_serverops_mcp import CONFIG_SCHEMA_VERSION
from codex_serverops_mcp.errors import ConfigurationError, ConfigVersionError

from .model import Authentication, ConnectionType, ElevationMode, ServerOpsConfig, ServerProfile

FORBIDDEN_SECRET_FIELDS = {
    "password",
    "sudo_password",
    "key_passphrase",
    "private_key_content",
}
PROFILE_FIELDS = {
    "display_name",
    "connection_type",
    "authentication",
    "ssh_host",
    "host",
    "port",
    "user",
    "identity_file",
    "allowed_roots",
    "allow_terminal",
    "allow_file_read",
    "allow_file_write",
    "elevation_mode",
    "allow_root_session",
    "environment",
    "command_timeout_seconds",
    "max_output_bytes",
}


def _expect_string(raw: Mapping[str, object], name: str, *, required: bool = False) -> str | None:
    value = raw.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{name} must be a string")
    return value


def _expect_bool(raw: Mapping[str, object], name: str, default: bool) -> bool:
    value = raw.get(name, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{name} must be true or false")
    return value


def _expect_int(raw: Mapping[str, object], name: str, default: int | None = None) -> int | None:
    value = raw.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{name} must be an integer")
    return value


def _expect_enum[T: str](enum_type: type[T], value: object, name: str) -> T:
    if not isinstance(value, str):
        raise ConfigurationError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        choices = ", ".join(member.value for member in enum_type)  # type: ignore[attr-defined]
        raise ConfigurationError(f"{name} must be one of: {choices}") from error


def _migrate(raw: dict[str, object]) -> tuple[dict[str, object], bool]:
    version = raw.get("schema_version", 0)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ConfigurationError("schema_version must be an integer")
    if version > CONFIG_SCHEMA_VERSION:
        raise ConfigVersionError(
            f"config schema {version} is newer than supported schema {CONFIG_SCHEMA_VERSION}"
        )
    if version < 0:
        raise ConfigVersionError("config schema version cannot be negative")

    migrated = False
    document = copy.deepcopy(raw)
    if version == 0:
        profiles = document.get("profiles", {})
        if not isinstance(profiles, dict):
            raise ConfigurationError("profiles must be a table")
        for profile in profiles.values():
            if not isinstance(profile, dict):
                raise ConfigurationError("every profile must be a table")
            if "sudo_mode" in profile:
                if "elevation_mode" in profile:
                    raise ConfigurationError(
                        "legacy sudo_mode conflicts with elevation_mode"
                    )
                profile["elevation_mode"] = profile.pop("sudo_mode")
        document["schema_version"] = 1
        version = 1
        migrated = True

    if version != CONFIG_SCHEMA_VERSION:
        raise ConfigVersionError(f"no migration path exists for config schema {version}")
    return document, migrated


def _parse_profile(name: str, raw_value: object) -> ServerProfile:
    if not isinstance(raw_value, dict):
        raise ConfigurationError(f"profile {name!r} must be a table")
    raw: dict[str, object] = raw_value
    forbidden = FORBIDDEN_SECRET_FIELDS.intersection(raw)
    if forbidden:
        fields = ", ".join(sorted(forbidden))
        raise ConfigurationError(f"profile {name!r} contains forbidden secret fields: {fields}")
    unknown = set(raw).difference(PROFILE_FIELDS)
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise ConfigurationError(f"profile {name!r} contains unknown fields: {fields}")

    roots_value = raw.get("allowed_roots", [])
    if not isinstance(roots_value, list) or not all(
        isinstance(value, str) for value in roots_value
    ):
        raise ConfigurationError("allowed_roots must be an array of strings")

    connection_type = _expect_enum(
        ConnectionType, raw.get("connection_type"), "connection_type"
    )
    authentication = _expect_enum(
        Authentication, raw.get("authentication"), "authentication"
    )
    elevation_mode = _expect_enum(
        ElevationMode,
        raw.get("elevation_mode", ElevationMode.DISABLED.value),
        "elevation_mode",
    )
    return ServerProfile(
        display_name=_expect_string(raw, "display_name", required=True) or "",
        connection_type=connection_type,
        authentication=authentication,
        ssh_host=_expect_string(raw, "ssh_host"),
        host=_expect_string(raw, "host"),
        port=_expect_int(raw, "port"),
        user=_expect_string(raw, "user"),
        identity_file=_expect_string(raw, "identity_file"),
        allowed_roots=tuple(roots_value),
        allow_terminal=_expect_bool(raw, "allow_terminal", True),
        allow_file_read=_expect_bool(raw, "allow_file_read", False),
        allow_file_write=_expect_bool(raw, "allow_file_write", False),
        elevation_mode=elevation_mode,
        allow_root_session=_expect_bool(raw, "allow_root_session", False),
        environment=_expect_string(raw, "environment") or "unspecified",
        command_timeout_seconds=_expect_int(raw, "command_timeout_seconds", 60) or 0,
        max_output_bytes=_expect_int(raw, "max_output_bytes", 2_097_152) or 0,
    )


def decode_config(text: str) -> tuple[ServerOpsConfig, bool]:
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"invalid TOML: {error}") from error
    document, migrated = _migrate(parsed)
    unknown_root = set(document).difference({"schema_version", "profiles"})
    if unknown_root:
        fields = ", ".join(sorted(unknown_root))
        raise ConfigurationError(f"config contains unknown top-level fields: {fields}")
    profiles_value = document.get("profiles", {})
    if not isinstance(profiles_value, dict):
        raise ConfigurationError("profiles must be a table")
    profiles = {
        name: _parse_profile(name, raw_profile)
        for name, raw_profile in profiles_value.items()
    }
    return ServerOpsConfig(profiles=profiles), migrated


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_value(value: str | int | bool | tuple[str, ...]) -> str:
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return "[" + ", ".join(_toml_string(item) for item in value) + "]"


def encode_config(config: ServerOpsConfig) -> str:
    lines = [f"schema_version = {CONFIG_SCHEMA_VERSION}"]
    for name in sorted(config.profiles):
        profile = config.profiles[name]
        lines.extend(("", f"[profiles.{_toml_string(name)}]"))
        fields: tuple[tuple[str, str | int | bool | tuple[str, ...] | None], ...] = (
            ("display_name", profile.display_name),
            ("connection_type", profile.connection_type.value),
            ("authentication", profile.authentication.value),
            ("ssh_host", profile.ssh_host),
            ("host", profile.host),
            ("port", profile.port),
            ("user", profile.user),
            ("identity_file", profile.identity_file),
            ("allowed_roots", profile.allowed_roots),
            ("allow_terminal", profile.allow_terminal),
            ("allow_file_read", profile.allow_file_read),
            ("allow_file_write", profile.allow_file_write),
            ("elevation_mode", profile.elevation_mode.value),
            ("allow_root_session", profile.allow_root_session),
            ("environment", profile.environment),
            ("command_timeout_seconds", profile.command_timeout_seconds),
            ("max_output_bytes", profile.max_output_bytes),
        )
        lines.extend(
            f"{field_name} = {_toml_value(value)}"
            for field_name, value in fields
            if value is not None
        )
    return "\n".join(lines) + "\n"
