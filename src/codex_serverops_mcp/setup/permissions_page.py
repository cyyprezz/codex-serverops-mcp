from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from codex_serverops_mcp.config import ElevationMode

from .form_state import ELEVATION_LABELS, ProfileFormState
from .form_widgets import page_heading


class PermissionsPage(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        state: ProfileFormState,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, style="SetupCard.TFrame")
        self.state = state
        self.on_change = on_change
        self.advanced_visible = tk.BooleanVar(self, value=False)
        self.columnconfigure(0, weight=1)
        row = page_heading(
            self,
            "Was darf Codex auf diesem Server tun?",
            "Diese Auswahl steuert die geführten Werkzeuge. Maßgeblich bleiben immer "
            "die Linux-Rechte.",
        )
        self._build_access(row)
        row += 1
        self._build_roots(row)
        row += 1
        self._build_elevation(row)
        row += 1
        self._build_context(row)
        row += 1
        self._build_advanced(row)
        self.refresh()

    def _build_access(self, row: int) -> None:
        access = ttk.LabelFrame(self, text="Zugriff", padding=12)
        access.grid(row=row, column=0, sticky="ew")
        ttk.Checkbutton(
            access,
            text="Terminal und Befehle verwenden",
            variable=self.state.allow_terminal,
            command=self._terminal_changed,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            access,
            text="Dateien strukturiert lesen",
            variable=self.state.allow_file_read,
            command=self._read_changed,
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            access,
            text="Dateien strukturiert ändern",
            variable=self.state.allow_file_write,
            command=self._write_changed,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))

    def _build_roots(self, row: int) -> None:
        self.roots_frame = ttk.LabelFrame(self, text="Ordner für Dateiwerkzeuge", padding=12)
        self.roots_frame.grid(row=row, column=0, sticky="ew", pady=(14, 0))
        self.roots_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.roots_frame,
            text="Ein Linux-Pfad pro Zeile, zum Beispiel /opt/app",
            style="SetupHelp.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.allowed_roots_text = tk.Text(self.roots_frame, height=4, wrap="none")
        self.allowed_roots_text.grid(row=1, column=0, sticky="ew", pady=(6, 4))
        self.allowed_roots_text.insert("1.0", self.state.initial_allowed_roots)
        ttk.Label(
            self.roots_frame,
            text=(
                "Diese Ordner gelten nur für die strukturierten Dateiwerkzeuge. "
                "Terminalbefehle werden dadurch nicht eingeschränkt."
            ),
            style="SetupHelp.TLabel",
            wraplength=650,
            justify="left",
        ).grid(row=2, column=0, sticky="w")

    def _build_elevation(self, row: int) -> None:
        admin = ttk.LabelFrame(self, text="Administratorrechte (optional)", padding=12)
        admin.grid(row=row, column=0, sticky="ew", pady=(14, 0))
        admin.columnconfigure(0, weight=1)
        elevation = ttk.Combobox(
            admin,
            textvariable=self.state.elevation_mode,
            values=tuple(ELEVATION_LABELS.values()),
            state="readonly",
        )
        elevation.grid(row=0, column=0, sticky="ew")
        elevation.bind("<<ComboboxSelected>>", self._elevation_changed)
        self.elevation_help = ttk.Label(
            admin,
            style="SetupHelp.TLabel",
            wraplength=650,
            justify="left",
        )
        self.elevation_help.grid(row=1, column=0, sticky="w", pady=(4, 8))
        self.root_check = ttk.Checkbutton(
            admin,
            text="Bei Bedarf eine getrennte Root-Sitzung anbieten",
            variable=self.state.allow_root_session,
            command=self._root_changed,
        )
        self.root_check.grid(row=2, column=0, sticky="w")

    def _build_context(self, row: int) -> None:
        context = ttk.LabelFrame(self, text="Kennzeichnung", padding=12)
        context.grid(row=row, column=0, sticky="ew", pady=(14, 0))
        context.columnconfigure(0, weight=1)
        ttk.Label(
            context,
            text="Umgebung, zum Beispiel test, staging oder production",
            style="SetupHelp.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            context,
            textvariable=self.state.environment,
            values=("unspecified", "test", "development", "staging", "production"),
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))

    def _build_advanced(self, row: int) -> None:
        ttk.Checkbutton(
            self,
            text="Erweiterte technische Einstellungen anzeigen",
            variable=self.advanced_visible,
            command=self.refresh,
        ).grid(row=row, column=0, sticky="w", pady=(16, 0))
        self.advanced = ttk.LabelFrame(self, text="Technische Grenzwerte", padding=12)
        self.advanced.grid(row=row + 1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(self.advanced, text="Befehls-Timeout in Sekunden").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Entry(self.advanced, textvariable=self.state.command_timeout, width=12).grid(
            row=0,
            column=1,
            padx=(10, 24),
        )
        ttk.Label(self.advanced, text="Maximale Ausgabe in Bytes").grid(
            row=0,
            column=2,
            sticky="w",
        )
        ttk.Entry(self.advanced, textvariable=self.state.max_output, width=14).grid(
            row=0,
            column=3,
            padx=(10, 0),
        )

    def allowed_roots(self) -> str:
        return self.allowed_roots_text.get("1.0", "end-1c")

    def _terminal_changed(self) -> None:
        if not self.state.allow_terminal.get():
            self.state.allow_root_session.set(False)
        self.refresh()
        self.on_change()

    def _read_changed(self) -> None:
        if not self.state.allow_file_read.get():
            self.state.allow_file_write.set(False)
        self.refresh()
        self.on_change()

    def _write_changed(self) -> None:
        if self.state.allow_file_write.get():
            self.state.allow_file_read.set(True)
        self.refresh()
        self.on_change()

    def _elevation_changed(self, _event: object) -> None:
        if self.state.elevation is ElevationMode.DISABLED:
            self.state.allow_root_session.set(False)
        self.refresh()
        self.on_change()

    def _root_changed(self) -> None:
        if self.state.allow_root_session.get():
            self.state.allow_terminal.set(True)
        self.refresh()
        self.on_change()

    def refresh(self) -> None:
        file_access = self.state.allow_file_read.get() or self.state.allow_file_write.get()
        if file_access:
            self.roots_frame.grid()
        else:
            self.roots_frame.grid_remove()
        elevation = self.state.elevation
        descriptions = {
            ElevationMode.DISABLED: "ServerOps bietet keine geführten sudo-Aktionen an.",
            ElevationMode.NON_INTERACTIVE: (
                "Es werden nur sudo-Befehle ausgeführt, die serverseitig kein Passwort verlangen."
            ),
            ElevationMode.INTERACTIVE: (
                "Ein sudo-Passwort wird einmal im kleinen sicheren Fenster abgefragt und danach "
                "über den serverseitigen sudo-Cache wiederverwendet."
            ),
        }
        self.elevation_help.configure(text=descriptions[elevation])
        if elevation is ElevationMode.DISABLED:
            self.root_check.grid_remove()
        else:
            self.root_check.grid()
        if self.advanced_visible.get():
            self.advanced.grid()
        else:
            self.advanced.grid_remove()
