from __future__ import annotations

from .model import ServerProfile


def profile_summary(name: str, profile: ServerProfile) -> dict[str, object]:
    return {
        "name": name,
        "display_name": profile.display_name,
        "connection_type": profile.connection_type.value,
        "target": profile.ssh_host or profile.host,
        "environment": profile.environment,
        "allow_terminal": profile.allow_terminal,
        "allow_file_read": profile.allow_file_read,
        "allow_file_write": profile.allow_file_write,
        "elevation_mode": profile.elevation_mode.value,
    }


def profile_details(name: str, profile: ServerProfile) -> dict[str, object]:
    return {
        **profile_summary(name, profile),
        "ssh_host": profile.ssh_host,
        "host": profile.host,
        "port": profile.port,
        "user": profile.user,
        "identity_file": profile.identity_file,
        "authentication": profile.authentication.value,
        "allowed_roots": list(profile.allowed_roots),
        "allow_root_session": profile.allow_root_session,
        "command_timeout_seconds": profile.command_timeout_seconds,
        "max_output_bytes": profile.max_output_bytes,
    }
