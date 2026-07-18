from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerProfile,
)

from .keys import default_private_key_path


class CredentialMode(StrEnum):
    PASSWORD = "password"
    OPENSSH = "openssh"
    EXISTING_KEY = "existing_key"
    NEW_KEY = "new_key"


@dataclass(frozen=True, slots=True)
class ProfileDraft:
    profile_name: str
    profile: ServerProfile
    password_profile: ServerProfile | None
    credential_mode: CredentialMode
    install_public_key: bool
    private_key_path: Path | None
    public_key_path: Path | None


def build_profile_draft(
    *,
    profile_name: str,
    display_name: str,
    connection_type: str,
    target: str,
    user: str,
    port: str,
    credential_mode: str,
    identity_file: str,
    public_key_file: str,
    install_public_key: bool,
    allowed_roots: str,
    allow_terminal: bool,
    allow_file_read: bool,
    allow_file_write: bool,
    elevation_mode: str,
    allow_root_session: bool,
    environment: str,
    command_timeout: str,
    max_output: str,
) -> ProfileDraft:
    name = profile_name.strip()
    connection = ConnectionType(connection_type)
    credential = CredentialMode(credential_mode)
    identity = _identity_path(name, credential, identity_file)
    if credential is CredentialMode.PASSWORD and connection is ConnectionType.SSH_CONFIG:
        raise ValueError("SSH-Aliase verwenden die vorhandene OpenSSH-Authentifizierung.")
    authentication = (
        Authentication.INTERACTIVE_PASSWORD
        if credential is CredentialMode.PASSWORD
        else Authentication.OPENSSH
    )
    roots = tuple(line.strip() for line in allowed_roots.splitlines() if line.strip())
    target_value = target.strip()
    direct = connection is ConnectionType.DIRECT
    profile = ServerProfile(
        display_name=display_name.strip(),
        connection_type=connection,
        authentication=authentication,
        ssh_host=None if direct else target_value,
        host=target_value if direct else None,
        port=int(port) if direct else None,
        user=user.strip() if direct else None,
        identity_file=str(identity) if identity is not None else None,
        allowed_roots=roots,
        allow_terminal=allow_terminal,
        allow_file_read=allow_file_read,
        allow_file_write=allow_file_write,
        elevation_mode=ElevationMode(elevation_mode),
        allow_root_session=allow_root_session,
        environment=environment.strip(),
        command_timeout_seconds=int(command_timeout),
        max_output_bytes=int(max_output),
    )
    if install_public_key and (
        not direct or credential not in {CredentialMode.EXISTING_KEY, CredentialMode.NEW_KEY}
    ):
        raise ValueError(
            "Die automatische Schlüsselinstallation benötigt ein direktes Ziel und einen Schlüssel."
        )
    public_path = _public_key_path(
        install_public_key,
        credential,
        identity,
        public_key_file,
    )
    password_profile = None
    if install_public_key:
        password_profile = replace(
            profile,
            authentication=Authentication.INTERACTIVE_PASSWORD,
            identity_file=None,
        )
    return ProfileDraft(
        name,
        profile,
        password_profile,
        credential,
        install_public_key,
        identity,
        public_path,
    )


def profile_confirmation_text(draft: ProfileDraft) -> str:
    profile = draft.profile
    target = profile.ssh_host or f"{profile.user}@{profile.host}:{profile.port}"
    roots = ", ".join(profile.allowed_roots) or "keine strukturierten Dateipfade"
    return (
        f"Profil: {draft.profile_name}\n"
        f"Anzeige: {profile.display_name}\n"
        f"Ziel: {target}\n"
        f"Authentifizierung: {profile.authentication.value}\n"
        f"Dateipfade: {roots}\n"
        f"Terminal: {'ja' if profile.allow_terminal else 'nein'}\n"
        f"Elevation: {profile.elevation_mode.value}\n"
        f"Umgebung: {profile.environment}\n\n"
        "Dies ist keine Sandbox. Maßgeblich bleiben SSH-Benutzer, Dateirechte und sudoers."
    )


def _identity_path(
    profile_name: str,
    credential: CredentialMode,
    identity_file: str,
) -> Path | None:
    if credential not in {CredentialMode.EXISTING_KEY, CredentialMode.NEW_KEY}:
        return None
    raw_identity = identity_file.strip()
    if not raw_identity and credential is CredentialMode.NEW_KEY:
        raw_identity = str(default_private_key_path(profile_name))
    if not raw_identity:
        raise ValueError("Eine private Schlüsseldatei muss ausgewählt werden.")
    identity = Path(raw_identity).expanduser().resolve()
    if credential is CredentialMode.EXISTING_KEY and not identity.is_file():
        raise ValueError("Die ausgewählte private Schlüsseldatei existiert nicht.")
    return identity


def _public_key_path(
    install: bool,
    credential: CredentialMode,
    identity: Path | None,
    public_key_file: str,
) -> Path | None:
    if not install or credential is CredentialMode.NEW_KEY:
        return None
    if identity is None:
        raise ValueError("Die private Schlüsseldatei fehlt.")
    raw_public = public_key_file.strip()
    public_path = (
        Path(raw_public).expanduser().resolve()
        if raw_public
        else identity.with_name(f"{identity.name}.pub")
    )
    if not public_path.is_file():
        raise ValueError("Die öffentliche Schlüsseldatei wurde nicht gefunden.")
    return public_path
