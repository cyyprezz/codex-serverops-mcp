from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk

from codex_serverops_mcp.config import ConnectionType

from .draft import CredentialMode
from .form_state import CREDENTIAL_LABELS, ProfileFormState
from .form_widgets import page_heading


class AuthenticationPage(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        state: ProfileFormState,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, style="SetupCard.TFrame")
        self.state = state
        self.on_change = on_change
        self.columnconfigure(0, weight=1)
        row = page_heading(
            self,
            "Wie meldet sich ServerOps an?",
            "Geheimnisse bleiben in lokalen Fenstern und werden nie an Codex zurückgegeben.",
        )
        self.alias_notice = ttk.LabelFrame(self, text="Über den SSH-Alias", padding=14)
        self.alias_notice.grid(row=row, column=0, sticky="ew")
        ttk.Label(
            self.alias_notice,
            text=(
                "Benutzer, Port und Schlüssel kommen vollständig aus deiner vorhandenen "
                "OpenSSH-Konfiguration. Hier ist keine weitere Auswahl nötig."
            ),
            wraplength=650,
            justify="left",
        ).pack(anchor="w")
        self.method_frame = ttk.Frame(self, style="SetupCard.TFrame")
        self.method_frame.grid(row=row, column=0, sticky="ew")
        self.method_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.method_frame,
            text="Anmeldemethode",
            style="SetupField.TLabel",
        ).grid(row=0, column=0, sticky="w")
        method = ttk.Combobox(
            self.method_frame,
            textvariable=state.credential_mode,
            values=tuple(CREDENTIAL_LABELS.values()),
            state="readonly",
        )
        method.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        method.bind("<<ComboboxSelected>>", self._credential_changed)
        self.method_help = ttk.Label(
            self.method_frame,
            style="SetupHelp.TLabel",
            wraplength=690,
            justify="left",
        )
        self.method_help.grid(row=2, column=0, sticky="w", pady=(0, 16))
        self._build_key_fields()
        self._build_install_fields()
        self._build_passphrase_fields()
        self.refresh()

    def _build_key_fields(self) -> None:
        self.key_frame = ttk.Frame(self.method_frame, style="SetupCard.TFrame")
        self.key_frame.grid(row=3, column=0, sticky="ew")
        self.key_frame.columnconfigure(0, weight=1)
        self.key_label = ttk.Label(self.key_frame, style="SetupField.TLabel")
        self.key_label.grid(row=0, column=0, sticky="w")
        key_row = ttk.Frame(self.key_frame, style="SetupCard.TFrame")
        key_row.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        key_row.columnconfigure(0, weight=1)
        ttk.Entry(key_row, textvariable=self.state.identity_file).grid(
            row=0,
            column=0,
            sticky="ew",
        )
        self.key_button = ttk.Button(key_row, command=self._choose_key)
        self.key_button.grid(row=0, column=1, padx=(8, 0))
        self.key_help = ttk.Label(
            self.key_frame,
            style="SetupHelp.TLabel",
            wraplength=690,
            justify="left",
        )
        self.key_help.grid(row=2, column=0, sticky="w", pady=(0, 12))

    def _build_install_fields(self) -> None:
        self.install_check = ttk.Checkbutton(
            self.method_frame,
            text="Öffentlichen Schlüssel jetzt auf dem Server einrichten",
            variable=self.state.install_public_key,
            command=self._install_changed,
        )
        self.install_check.grid(row=4, column=0, sticky="w", pady=(2, 2))
        self.install_help = ttk.Label(
            self.method_frame,
            text=(
                "ServerOps meldet sich einmal per Passwort an, installiert nur den öffentlichen "
                "Schlüssel und testet anschließend eine neue Schlüsselanmeldung."
            ),
            style="SetupHelp.TLabel",
            wraplength=690,
            justify="left",
        )
        self.install_help.grid(row=5, column=0, sticky="w", pady=(0, 12))
        self.public_frame = ttk.Frame(self.method_frame, style="SetupCard.TFrame")
        self.public_frame.grid(row=6, column=0, sticky="ew")
        self.public_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.public_frame,
            text="Öffentliche Schlüsseldatei",
            style="SetupField.TLabel",
        ).grid(row=0, column=0, sticky="w")
        public_row = ttk.Frame(self.public_frame, style="SetupCard.TFrame")
        public_row.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        public_row.columnconfigure(0, weight=1)
        ttk.Entry(public_row, textvariable=self.state.public_key_file).grid(
            row=0,
            column=0,
            sticky="ew",
        )
        ttk.Button(public_row, text="Auswählen…", command=self._choose_public_key).grid(
            row=0,
            column=1,
            padx=(8, 0),
        )

    def _build_passphrase_fields(self) -> None:
        self.passphrase_frame = ttk.LabelFrame(
            self.method_frame,
            text="Optionaler Schutz für den neuen Schlüssel",
            padding=12,
        )
        self.passphrase_frame.grid(row=7, column=0, sticky="ew")
        self.passphrase_frame.columnconfigure(0, weight=1)
        ttk.Label(self.passphrase_frame, text="Passphrase (kann leer bleiben)").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Entry(
            self.passphrase_frame,
            textvariable=self.state.key_passphrase,
            show="●",
        ).grid(row=1, column=0, sticky="ew", pady=(4, 10))
        ttk.Label(self.passphrase_frame, text="Passphrase wiederholen").grid(
            row=2,
            column=0,
            sticky="w",
        )
        ttk.Entry(
            self.passphrase_frame,
            textvariable=self.state.key_passphrase_repeat,
            show="●",
        ).grid(row=3, column=0, sticky="ew", pady=(4, 0))

    def _credential_changed(self, _event: object) -> None:
        self.refresh()
        self.on_change()

    def _install_changed(self) -> None:
        self.refresh()
        self.on_change()

    def _choose_key(self) -> None:
        if self.state.credential is CredentialMode.NEW_KEY:
            selected = filedialog.asksaveasfilename(
                parent=self,
                title="Speicherort für den neuen SSH-Schlüssel",
                initialfile=f"{self.state.profile_name.get() or 'server'}_ed25519",
            )
        else:
            selected = filedialog.askopenfilename(
                parent=self,
                title="Privaten SSH-Schlüssel auswählen",
            )
        if selected:
            self.state.identity_file.set(selected)
            public = Path(selected).with_name(f"{Path(selected).name}.pub")
            if public.is_file():
                self.state.public_key_file.set(str(public))

    def _choose_public_key(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="Öffentlichen SSH-Schlüssel auswählen",
        )
        if selected:
            self.state.public_key_file.set(selected)

    def refresh(self) -> None:
        alias = self.state.connection is ConnectionType.SSH_CONFIG
        if alias:
            self.alias_notice.grid()
            self.method_frame.grid_remove()
            return
        self.alias_notice.grid_remove()
        self.method_frame.grid()
        credential = self.state.credential
        self._refresh_method_help(credential)
        has_key = credential in {CredentialMode.EXISTING_KEY, CredentialMode.NEW_KEY}
        self._refresh_key_fields(credential, has_key)
        self._refresh_optional_fields(credential, has_key)

    def _refresh_method_help(self, credential: CredentialMode) -> None:
        descriptions = {
            CredentialMode.PASSWORD: (
                "Bei jeder neuen SSH-Sitzung erscheint das kleine Passwortfenster."
            ),
            CredentialMode.OPENSSH: (
                "OpenSSH verwendet seine üblichen Schlüssel, Konfigurationen und einen "
                "vorhandenen Agenten."
            ),
            CredentialMode.EXISTING_KEY: (
                "Wähle die private Schlüsseldatei. Eine Passphrase fragt ServerOps später lokal ab."
            ),
            CredentialMode.NEW_KEY: (
                "ServerOps erzeugt lokal einen neuen Ed25519-Schlüssel; der private Teil "
                "bleibt hier."
            ),
        }
        self.method_help.configure(text=descriptions[credential])

    def _refresh_key_fields(self, credential: CredentialMode, has_key: bool) -> None:
        if not has_key:
            self.key_frame.grid_remove()
            return
        self.key_frame.grid()
        new_key = credential is CredentialMode.NEW_KEY
        self.key_label.configure(
            text="Speicherort (optional)" if new_key else "Private Schlüsseldatei"
        )
        self.key_button.configure(text="Speicherort…" if new_key else "Auswählen…")
        self.key_help.configure(
            text=(
                "Leer lassen für den sicheren Standardordner unter .ssh/serverops."
                if new_key
                else "Der private Schlüssel wird ausschließlich von Windows OpenSSH gelesen."
            )
        )

    def _refresh_optional_fields(self, credential: CredentialMode, has_key: bool) -> None:
        if has_key:
            self.install_check.grid()
            self.install_help.grid()
        else:
            self.state.install_public_key.set(False)
            self.install_check.grid_remove()
            self.install_help.grid_remove()
        if credential is CredentialMode.EXISTING_KEY and self.state.install_public_key.get():
            self.public_frame.grid()
        else:
            self.public_frame.grid_remove()
        if credential is CredentialMode.NEW_KEY:
            self.passphrase_frame.grid()
        else:
            self.passphrase_frame.grid_remove()
