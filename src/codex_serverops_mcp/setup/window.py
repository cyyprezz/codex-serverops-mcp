from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk

from codex_serverops_mcp.config import ServerProfile
from codex_serverops_mcp.errors import ServerOpsError

from .draft import CredentialMode, ProfileDraft
from .form import ProfileForm
from .keys import Ed25519KeyGenerator, read_public_key
from .model import SetupAction, SetupRecord, SetupStatus
from .operations import ProfileSetupOperations
from .scrollable import ScrollableFormHost


class SetupWindow:
    def __init__(
        self,
        record: SetupRecord,
        operations: ProfileSetupOperations,
        key_generator: Ed25519KeyGenerator,
    ) -> None:
        self.record = record
        self.operations = operations
        self.key_generator = key_generator
        self.outcome: tuple[SetupStatus, dict[str, object] | None, str | None] | None = None
        self.root = tk.Tk()
        self.root.title("ServerOps – Server einrichten")
        self._configure_styles()
        self._configure_window()
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(750, lambda: self.root.attributes("-topmost", False))
        remaining_ms = max(1, round((record.request.expires_at - record.updated_at) * 1_000))
        self.root.after(remaining_ms, self._expire)
        self._build()

    def run(self) -> tuple[SetupStatus, dict[str, object] | None, str | None]:
        self.root.mainloop()
        return self.outcome or (SetupStatus.CANCELLED, None, "Setup was cancelled locally.")

    def _configure_window(self) -> None:
        if self.record.request.action in {SetupAction.ADD, SetupAction.EDIT}:
            self.root.geometry("900x720")
            self.root.minsize(780, 640)
        else:
            self.root.geometry("680x400")
            self.root.minsize(600, 340)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure("SetupTitle.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("SetupPageTitle.TLabel", font=("Segoe UI", 14, "bold"))
        style.configure("SetupStep.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("SetupField.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("SetupHelp.TLabel", foreground="#4b5563")
        style.configure("SetupReviewKey.TLabel", font=("Segoe UI", 9, "bold"))
        style.configure("SetupPrimary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))
        style.configure("SetupSecondary.TButton", padding=(12, 8))
        style.configure("SetupWarning.TFrame", background="#fff4e5")
        style.configure(
            "SetupWarningTitle.TLabel",
            background="#fff4e5",
            foreground="#7c2d12",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "SetupWarning.TLabel",
            background="#fff4e5",
            foreground="#7c2d12",
        )

    def _build(self) -> None:
        action = self.record.request.action
        if action in {SetupAction.ADD, SetupAction.EDIT}:
            self._build_form(action)
        elif action is SetupAction.REMOVE:
            self._build_single_action("Profil entfernen", self._remove)
        elif action is SetupAction.TEST:
            self._build_single_action("Verbindung testen", self._test)

    def _build_form(self, action: SetupAction) -> None:
        request = self.record.request
        profile = self._existing_profile() if action is SetupAction.EDIT else None
        shell = ttk.Frame(self.root, padding=(26, 22, 26, 18))
        shell.pack(fill="both", expand=True)
        title = "Serverprofil bearbeiten" if action is SetupAction.EDIT else "Server hinzufügen"
        ttk.Label(shell, text=title, style="SetupTitle.TLabel").pack(anchor="w")
        ttk.Label(
            shell,
            text=(
                "Vier kurze Schritte führen durch Verbindung, Anmeldung, Zugriff und Prüfung. "
                "Nur passende Einstellungen werden angezeigt."
            ),
            style="SetupHelp.TLabel",
            wraplength=800,
            justify="left",
        ).pack(anchor="w", pady=(4, 14))
        progress_row = ttk.Frame(shell)
        progress_row.pack(fill="x")
        self.step_label = ttk.Label(progress_row, style="SetupStep.TLabel")
        self.step_label.pack(side="left")
        self.step_title = ttk.Label(progress_row, style="SetupHelp.TLabel")
        self.step_title.pack(side="right")
        self.progress = ttk.Progressbar(shell, maximum=4, mode="determinate")
        self.progress.pack(fill="x", pady=(7, 14))
        self.form_host = ScrollableFormHost(shell)
        self.form_host.pack(fill="both", expand=True)
        self.form = ProfileForm(
            self.form_host.canvas,
            profile_name=request.profile_name,
            profile=profile,
            suggested_host=request.suggested_host,
            suggested_user=request.suggested_user,
            lock_profile_name=action is SetupAction.EDIT,
            on_step_change=self._update_navigation,
        )
        self.form_host.attach(self.form)
        ttk.Separator(shell).pack(fill="x", pady=(14, 12))
        buttons = ttk.Frame(shell)
        buttons.pack(fill="x")
        ttk.Button(
            buttons,
            text="Abbrechen",
            command=self._cancel,
            style="SetupSecondary.TButton",
        ).pack(side="left")
        self.back_button = ttk.Button(
            buttons,
            text="Zurück",
            command=self._back,
            style="SetupSecondary.TButton",
        )
        self.primary_button = ttk.Button(
            buttons,
            command=lambda: self._primary(action),
            style="SetupPrimary.TButton",
        )
        self.primary_button.pack(side="right")
        self.back_button.pack(side="right", padx=(0, 10))
        self._update_navigation()

    def _update_navigation(self) -> None:
        self.step_label.configure(
            text=f"Schritt {self.form.step_number} von {self.form.step_count}"
        )
        self.step_title.configure(text=self.form.step_name)
        self.progress.configure(value=self.form.step_number)
        self.back_button.configure(state="disabled" if self.form.is_first_step else "normal")
        if self.form.is_review_step:
            label = (
                "Änderungen speichern"
                if self.record.request.action is SetupAction.EDIT
                else "Profil anlegen"
            )
        else:
            label = "Weiter"
        self.primary_button.configure(text=label)
        self.form_host.scroll_to_top()

    def _primary(self, action: SetupAction) -> None:
        if self.form.is_review_step:
            self._save(action)
            return
        try:
            self.form.go_next()
        except Exception as error:
            self._show_error(error)

    def _back(self) -> None:
        self.form.go_back()

    def _build_single_action(self, label: str, command: object) -> None:
        profile_name = self.record.request.profile_name or ""
        profile = self._existing_profile()
        frame = ttk.Frame(self.root, padding=28)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=label, style="SetupTitle.TLabel").pack(anchor="w")
        target = profile.ssh_host or f"{profile.user}@{profile.host}:{profile.port}"
        ttk.Label(
            frame,
            text=f"{profile.display_name} ({profile_name})\nZiel: {target}",
            justify="left",
        ).pack(anchor="w", pady=(12, 18))
        ttk.Label(
            frame,
            text=(
                "Die Verbindung und mögliche Authentifizierungsabfragen laufen lokal. "
                "Geheimnisse werden nicht an Codex zurückgegeben."
            ),
            wraplength=600,
            justify="left",
            style="SetupHelp.TLabel",
        ).pack(anchor="w")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", side="bottom")
        ttk.Button(buttons, text="Abbrechen", command=self._cancel).pack(side="left")
        ttk.Button(buttons, text=label, command=command).pack(side="right")  # type: ignore[arg-type]

    def _save(self, action: SetupAction) -> None:
        try:
            draft = self.form.draft()
            result = self._persist_draft(action, draft)
        except Exception as error:
            self._show_error(error)
            return
        status = SetupStatus.CREATED if action is SetupAction.ADD else SetupStatus.UPDATED
        self._complete(status, result)

    def _persist_draft(
        self,
        action: SetupAction,
        draft: ProfileDraft,
    ) -> dict[str, object]:
        public_key: str | None = None
        if draft.credential_mode is CredentialMode.NEW_KEY:
            secret_source = self.form.take_key_secret()
            generated = self.key_generator.generate(
                draft.profile_name,
                secret_source,
                destination=draft.private_key_path,
            )
            draft = replace(
                draft,
                profile=replace(draft.profile, identity_file=str(generated.private_key_path)),
                private_key_path=generated.private_key_path,
                public_key_path=generated.public_key_path,
            )
            public_key = generated.public_key
        if draft.install_public_key:
            if draft.password_profile is None:
                raise RuntimeError("password staging profile is unavailable")
            public_key = public_key or read_public_key(self._required_public_path(draft))
            return self.operations.install_public_key_and_switch(
                draft.profile_name,
                draft.password_profile,
                draft.profile,
                public_key,
                replace_existing=action is SetupAction.EDIT,
            )
        if action is SetupAction.ADD:
            return self.operations.add(draft.profile_name, draft.profile)
        return self.operations.edit(draft.profile_name, draft.profile)

    def _remove(self) -> None:
        profile_name = self.record.request.profile_name or ""
        if not messagebox.askyesno(
            "ServerOps – Profil entfernen",
            (
                f"Profil '{profile_name}' wirklich aus der lokalen Konfiguration entfernen?\n\n"
                "Bereits laufende SSH-Sessions werden dadurch nicht automatisch umgebogen."
            ),
            parent=self.root,
        ):
            return
        try:
            result = self.operations.remove(profile_name)
        except Exception as error:
            self._show_error(error)
            return
        self._complete(SetupStatus.REMOVED, result)

    def _test(self) -> None:
        profile_name = self.record.request.profile_name or ""
        try:
            result = self.operations.test(profile_name)
        except Exception as error:
            self._show_error(error)
            return
        messagebox.showinfo(
            "ServerOps",
            "Die SSH-Verbindung und die gehaltene Bash-Shell wurden erfolgreich geprüft.",
            parent=self.root,
        )
        self._complete(SetupStatus.TESTED, result)

    def _existing_profile(self) -> ServerProfile:
        profile_name = self.record.request.profile_name or ""
        snapshot = self.operations.repository.load()
        try:
            return snapshot.config.profiles[profile_name]
        except KeyError as error:
            raise ValueError(f"Profil existiert nicht: {profile_name}") from error

    @staticmethod
    def _required_public_path(draft: ProfileDraft):
        if draft.public_key_path is None:
            raise ValueError("Die öffentliche Schlüsseldatei fehlt.")
        return draft.public_key_path

    def _show_error(self, error: Exception) -> None:
        message = (
            str(error)
            if isinstance(error, (ServerOpsError, ValueError))
            else "Der lokale Vorgang ist fehlgeschlagen. Die Profiländerung wurde nicht bestätigt."
        )
        messagebox.showerror("ServerOps", message, parent=self.root)

    def _cancel(self) -> None:
        self._complete(SetupStatus.CANCELLED, None, "Setup was cancelled locally.")

    def _expire(self) -> None:
        self._complete(SetupStatus.EXPIRED, None, "The local setup request expired.")

    def _complete(
        self,
        status: SetupStatus,
        result: dict[str, object] | None,
        message: str | None = None,
    ) -> None:
        if self.outcome is not None:
            return
        self.outcome = (status, result, message)
        self.root.destroy()
