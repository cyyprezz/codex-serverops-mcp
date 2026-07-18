from __future__ import annotations

import tkinter as tk

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerProfile,
)

from .draft import CredentialMode, ProfileDraft, build_profile_draft
from .keys import OneShotSecretSource

CONNECTION_LABELS = {
    ConnectionType.DIRECT.value: "Server direkt angeben",
    ConnectionType.SSH_CONFIG.value: "Vorhandenen SSH-Alias verwenden",
}
CREDENTIAL_LABELS = {
    CredentialMode.PASSWORD.value: "Passwort beim Verbinden verwenden",
    CredentialMode.OPENSSH.value: "OpenSSH-Standard verwenden",
    CredentialMode.EXISTING_KEY.value: "Vorhandenen SSH-Schlüssel verwenden",
    CredentialMode.NEW_KEY.value: "Neuen SSH-Schlüssel erstellen",
}
ELEVATION_LABELS = {
    ElevationMode.DISABLED.value: "Keine geführten Administratoraktionen",
    ElevationMode.NON_INTERACTIVE.value: "Nur bereits passwortlos erlaubtes sudo",
    ElevationMode.INTERACTIVE.value: "sudo bei Bedarf im sicheren Fenster freigeben",
}


class ProfileFormState:
    def __init__(
        self,
        master: tk.Misc,
        *,
        profile_name: str | None,
        profile: ServerProfile | None,
        suggested_host: str | None,
        suggested_user: str | None,
    ) -> None:
        connection = profile.connection_type if profile else ConnectionType.DIRECT
        credential = self._credential_mode(profile)
        default_name = profile.display_name if profile else suggested_host or ""
        self.profile_name = tk.StringVar(master, value=profile_name or "")
        self.display_name = tk.StringVar(master, value=default_name)
        self.connection_type = tk.StringVar(master, value=CONNECTION_LABELS[connection.value])
        self.target = tk.StringVar(
            master,
            value=(profile.ssh_host or profile.host or "") if profile else suggested_host or "",
        )
        self.user = tk.StringVar(
            master,
            value=profile.user if profile and profile.user else suggested_user or "",
        )
        self.port = tk.StringVar(master, value=str((profile.port if profile else None) or 22))
        self.credential_mode = tk.StringVar(master, value=CREDENTIAL_LABELS[credential.value])
        self.identity_file = tk.StringVar(
            master,
            value=profile.identity_file or "" if profile else "",
        )
        self.public_key_file = tk.StringVar(master, value="")
        self.install_public_key = tk.BooleanVar(master, value=False)
        self.initial_allowed_roots = "\n".join(profile.allowed_roots) if profile else ""
        self.allow_terminal = tk.BooleanVar(
            master,
            value=profile.allow_terminal if profile else True,
        )
        self.allow_file_read = tk.BooleanVar(
            master,
            value=profile.allow_file_read if profile else False,
        )
        self.allow_file_write = tk.BooleanVar(
            master,
            value=profile.allow_file_write if profile else False,
        )
        initial_elevation = (profile.elevation_mode if profile else ElevationMode.DISABLED).value
        self.elevation_mode = tk.StringVar(master, value=ELEVATION_LABELS[initial_elevation])
        self.allow_root_session = tk.BooleanVar(
            master,
            value=profile.allow_root_session if profile else False,
        )
        self.environment = tk.StringVar(
            master,
            value=profile.environment if profile else "unspecified",
        )
        self.command_timeout = tk.StringVar(
            master,
            value=str(profile.command_timeout_seconds if profile else 60),
        )
        self.max_output = tk.StringVar(
            master,
            value=str(profile.max_output_bytes if profile else 2_097_152),
        )
        self.key_passphrase = tk.StringVar(master, value="")
        self.key_passphrase_repeat = tk.StringVar(master, value="")

    @property
    def connection(self) -> ConnectionType:
        return ConnectionType(self._selected_key(CONNECTION_LABELS, self.connection_type.get()))

    @property
    def credential(self) -> CredentialMode:
        return CredentialMode(self._selected_key(CREDENTIAL_LABELS, self.credential_mode.get()))

    @property
    def elevation(self) -> ElevationMode:
        return ElevationMode(self._selected_key(ELEVATION_LABELS, self.elevation_mode.get()))

    def normalize_connection(self) -> None:
        if self.connection is ConnectionType.SSH_CONFIG:
            self.credential_mode.set(CREDENTIAL_LABELS[CredentialMode.OPENSSH.value])
            self.install_public_key.set(False)

    def draft(self, allowed_roots: str) -> ProfileDraft:
        return self._build_draft(
            allowed_roots=allowed_roots,
            allow_terminal=self.allow_terminal.get(),
            allow_file_read=self.allow_file_read.get(),
            allow_file_write=self.allow_file_write.get(),
            elevation_mode=self.elevation.value,
            allow_root_session=self.allow_root_session.get(),
            environment=self.environment.get(),
            command_timeout=self.command_timeout.get(),
            max_output=self.max_output.get(),
        )

    def validate_connection(self) -> None:
        self._build_draft(
            allowed_roots="",
            allow_terminal=True,
            allow_file_read=False,
            allow_file_write=False,
            elevation_mode=ElevationMode.DISABLED.value,
            allow_root_session=False,
            environment="unspecified",
            command_timeout="60",
            max_output="2097152",
            credential_mode=CredentialMode.PASSWORD.value,
            identity_file="",
            public_key_file="",
            install_public_key=False,
        )

    def validate_authentication(self) -> None:
        self._build_draft(
            allowed_roots="",
            allow_terminal=True,
            allow_file_read=False,
            allow_file_write=False,
            elevation_mode=ElevationMode.DISABLED.value,
            allow_root_session=False,
            environment="unspecified",
            command_timeout="60",
            max_output="2097152",
        )
        if self.key_passphrase.get() != self.key_passphrase_repeat.get():
            raise ValueError("Die beiden Passphrasen stimmen nicht überein.")

    def take_key_secret(self) -> OneShotSecretSource:
        first = self.key_passphrase.get()
        second = self.key_passphrase_repeat.get()
        self.key_passphrase.set("")
        self.key_passphrase_repeat.set("")
        if first != second:
            raise ValueError("Die beiden Passphrasen stimmen nicht überein.")
        value = bytearray(first.encode("utf-8"))
        first = ""
        second = ""
        return OneShotSecretSource(value)

    def _build_draft(
        self,
        *,
        allowed_roots: str,
        allow_terminal: bool,
        allow_file_read: bool,
        allow_file_write: bool,
        elevation_mode: str,
        allow_root_session: bool,
        environment: str,
        command_timeout: str,
        max_output: str,
        credential_mode: str | None = None,
        identity_file: str | None = None,
        public_key_file: str | None = None,
        install_public_key: bool | None = None,
    ) -> ProfileDraft:
        connection = self.connection
        credential = (
            CredentialMode.OPENSSH.value
            if connection is ConnectionType.SSH_CONFIG
            else credential_mode or self.credential.value
        )
        return build_profile_draft(
            profile_name=self.profile_name.get(),
            display_name=self.display_name.get(),
            connection_type=connection.value,
            target=self.target.get(),
            user=self.user.get(),
            port=self.port.get(),
            credential_mode=credential,
            identity_file=self.identity_file.get() if identity_file is None else identity_file,
            public_key_file=(
                self.public_key_file.get() if public_key_file is None else public_key_file
            ),
            install_public_key=(
                self.install_public_key.get()
                if install_public_key is None
                else install_public_key
            ),
            allowed_roots=allowed_roots,
            allow_terminal=allow_terminal,
            allow_file_read=allow_file_read,
            allow_file_write=allow_file_write,
            elevation_mode=elevation_mode,
            allow_root_session=allow_root_session,
            environment=environment,
            command_timeout=command_timeout,
            max_output=max_output,
        )

    @staticmethod
    def _credential_mode(profile: ServerProfile | None) -> CredentialMode:
        if profile is None:
            return CredentialMode.PASSWORD
        if profile.identity_file:
            return CredentialMode.EXISTING_KEY
        if profile.authentication is Authentication.INTERACTIVE_PASSWORD:
            return CredentialMode.PASSWORD
        return CredentialMode.OPENSSH

    @staticmethod
    def _selected_key(labels: dict[str, str], selected: str) -> str:
        for value, label in labels.items():
            if selected == label:
                return value
        raise ValueError("Die ausgewählte Option ist ungültig.")
