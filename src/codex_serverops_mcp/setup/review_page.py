from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from codex_serverops_mcp.config import ConnectionType

from .draft import ProfileDraft
from .form_state import CREDENTIAL_LABELS, ELEVATION_LABELS
from .form_widgets import page_heading


class ReviewPage(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, style="SetupCard.TFrame")
        self.columnconfigure(0, weight=1)
        self.content = ttk.Frame(self, style="SetupCard.TFrame")
        self.content.grid(row=2, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        page_heading(
            self,
            "Alles richtig eingestellt?",
            "Prüfe die wichtigsten Angaben. Mit „Profil anlegen“ bestätigst du lokal "
            "diese Auswahl.",
        )

    def render(self, draft: ProfileDraft) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        profile = draft.profile
        target = (
            profile.ssh_host
            if profile.connection_type is ConnectionType.SSH_CONFIG
            else f"{profile.user}@{profile.host}:{profile.port}"
        )
        rows = (
            ("Profil", f"{profile.display_name}  ·  {draft.profile_name}"),
            ("Verbindung", target or "–"),
            ("Anmeldung", CREDENTIAL_LABELS[draft.credential_mode.value]),
            ("Umgebung", profile.environment),
        )
        self._section(0, "Server", rows)
        capabilities: list[tuple[str, str]] = [
            ("Terminal", "Erlaubt" if profile.allow_terminal else "Nicht angeboten"),
            ("Dateien lesen", "Erlaubt" if profile.allow_file_read else "Nicht angeboten"),
            ("Dateien ändern", "Erlaubt" if profile.allow_file_write else "Nicht angeboten"),
        ]
        if profile.allowed_roots:
            capabilities.append(("Dateiordner", "\n".join(profile.allowed_roots)))
        self._section(1, "Zugriff", tuple(capabilities))
        elevation_rows = (
            ("sudo", ELEVATION_LABELS[profile.elevation_mode.value]),
            ("Root-Sitzung", "Angeboten" if profile.allow_root_session else "Nicht angeboten"),
        )
        self._section(2, "Administratorrechte", elevation_rows)
        warning = ttk.Frame(self.content, style="SetupWarning.TFrame", padding=14)
        warning.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        warning.columnconfigure(0, weight=1)
        ttk.Label(
            warning,
            text="Wichtiger Sicherheitshinweis",
            style="SetupWarningTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            warning,
            text=(
                "Terminalbefehle laufen mit den tatsächlichen Rechten des SSH-Benutzers. "
                "Ordnerauswahl und sudo-Einstellungen sind keine serverseitige Sandbox."
            ),
            style="SetupWarning.TLabel",
            wraplength=650,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _section(
        self,
        row: int,
        title: str,
        values: tuple[tuple[str, str], ...],
    ) -> None:
        frame = ttk.LabelFrame(self.content, text=title, padding=12)
        frame.grid(row=row, column=0, sticky="ew", pady=(0 if row == 0 else 10, 0))
        frame.columnconfigure(1, weight=1)
        for index, (label, value) in enumerate(values):
            ttk.Label(frame, text=label, style="SetupReviewKey.TLabel").grid(
                row=index,
                column=0,
                sticky="nw",
                padx=(0, 18),
                pady=3,
            )
            ttk.Label(frame, text=value, wraplength=520, justify="left").grid(
                row=index,
                column=1,
                sticky="nw",
                pady=3,
            )
