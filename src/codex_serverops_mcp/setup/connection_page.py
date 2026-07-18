from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from codex_serverops_mcp.config import ConnectionType

from .form_state import CONNECTION_LABELS, ProfileFormState
from .form_widgets import entry_field, page_heading


class ConnectionPage(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        state: ProfileFormState,
        on_change: Callable[[], None],
        *,
        lock_profile_name: bool,
    ) -> None:
        super().__init__(parent, style="SetupCard.TFrame")
        self.state = state
        self.on_change = on_change
        self.columnconfigure(0, weight=1)
        row = page_heading(
            self,
            "Welcher Server soll eingerichtet werden?",
            "Gib dem Profil einen verständlichen Namen und wähle, wie OpenSSH das Ziel findet.",
        )
        entry_field(
            self,
            row,
            "Profil-Kürzel",
            state.profile_name,
            "Kurzes eindeutiges Kürzel ohne Leerzeichen, zum Beispiel „shop-prod“.",
            disabled=lock_profile_name,
        )
        row += 3
        entry_field(
            self,
            row,
            "Anzeigename",
            state.display_name,
            "Dieser Name wird später in Codex und in Bestätigungen angezeigt.",
        )
        row += 3
        ttk.Label(self, text="Verbindungsart", style="SetupField.TLabel").grid(
            row=row,
            column=0,
            sticky="w",
        )
        connection = ttk.Combobox(
            self,
            textvariable=state.connection_type,
            values=tuple(CONNECTION_LABELS.values()),
            state="readonly",
        )
        connection.grid(row=row + 1, column=0, sticky="ew", pady=(4, 14))
        connection.bind("<<ComboboxSelected>>", self._connection_changed)
        row += 2
        self.target_label = ttk.Label(self, style="SetupField.TLabel")
        self.target_label.grid(row=row, column=0, sticky="w")
        ttk.Entry(self, textvariable=state.target).grid(
            row=row + 1,
            column=0,
            sticky="ew",
            pady=(4, 2),
        )
        self.target_help = ttk.Label(
            self,
            style="SetupHelp.TLabel",
            wraplength=690,
            justify="left",
        )
        self.target_help.grid(row=row + 2, column=0, sticky="w", pady=(0, 14))
        row += 3
        self.direct_fields = ttk.Frame(self, style="SetupCard.TFrame")
        self.direct_fields.grid(row=row, column=0, sticky="ew")
        self.direct_fields.columnconfigure(0, weight=1)
        entry_field(
            self.direct_fields,
            0,
            "Linux-Benutzer",
            state.user,
            "Nicht-root-Benutzer, mit dem ServerOps Befehle ausführt.",
        )
        port_frame = ttk.Frame(self.direct_fields, style="SetupCard.TFrame")
        port_frame.grid(row=3, column=0, sticky="w")
        ttk.Label(port_frame, text="SSH-Port", style="SetupField.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Entry(port_frame, textvariable=state.port, width=10).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 2),
        )
        ttk.Label(port_frame, text="Standard ist 22.", style="SetupHelp.TLabel").grid(
            row=2,
            column=0,
            sticky="w",
        )
        self.refresh()

    def _connection_changed(self, _event: object) -> None:
        self.state.normalize_connection()
        self.refresh()
        self.on_change()

    def refresh(self) -> None:
        direct = self.state.connection is ConnectionType.DIRECT
        self.target_label.configure(text="Server-Adresse" if direct else "SSH-Alias")
        self.target_help.configure(
            text=(
                "IP-Adresse oder Hostname, zum Beispiel 192.168.1.50 oder server.example.org."
                if direct
                else "Name aus deiner bestehenden OpenSSH-Konfiguration, zum Beispiel etesia-prod."
            )
        )
        if direct:
            self.direct_fields.grid()
        else:
            self.direct_fields.grid_remove()
