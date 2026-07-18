from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from codex_serverops_mcp.config import ServerProfile

from .authentication_page import AuthenticationPage
from .connection_page import ConnectionPage
from .draft import ProfileDraft, profile_confirmation_text
from .form_state import ProfileFormState
from .keys import OneShotSecretSource
from .permissions_page import PermissionsPage
from .review_page import ReviewPage

STEP_NAMES = ("Verbindung", "Anmeldung", "Zugriff", "Prüfen")


class ProfileForm(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        profile_name: str | None = None,
        profile: ServerProfile | None = None,
        suggested_host: str | None = None,
        suggested_user: str | None = None,
        lock_profile_name: bool = False,
        on_step_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, padding=(22, 18), style="SetupCard.TFrame")
        self.state = ProfileFormState(
            self,
            profile_name=profile_name,
            profile=profile,
            suggested_host=suggested_host,
            suggested_user=suggested_user,
        )
        self.state.normalize_connection()
        self.on_step_change = on_step_change or (lambda: None)
        self.current_step = 0
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.connection_page = ConnectionPage(
            self,
            self.state,
            self._fields_changed,
            lock_profile_name=lock_profile_name,
        )
        self.authentication_page = AuthenticationPage(
            self,
            self.state,
            self._fields_changed,
        )
        self.permissions_page = PermissionsPage(
            self,
            self.state,
            self._fields_changed,
        )
        self.review_page = ReviewPage(self)
        self.pages: tuple[ttk.Frame, ...] = (
            self.connection_page,
            self.authentication_page,
            self.permissions_page,
            self.review_page,
        )
        for page in self.pages:
            page.grid(row=0, column=0, sticky="nsew")
        self._show_current_page()

    @property
    def step_name(self) -> str:
        return STEP_NAMES[self.current_step]

    @property
    def step_number(self) -> int:
        return self.current_step + 1

    @property
    def step_count(self) -> int:
        return len(self.pages)

    @property
    def is_first_step(self) -> bool:
        return self.current_step == 0

    @property
    def is_review_step(self) -> bool:
        return self.current_step == len(self.pages) - 1

    def go_next(self) -> None:
        if self.is_review_step:
            return
        if self.current_step == 0:
            self.state.validate_connection()
        elif self.current_step == 1:
            self.state.validate_authentication()
        elif self.current_step == 2:
            self.review_page.render(self.draft())
        self.current_step += 1
        self._show_current_page()
        self.on_step_change()

    def go_back(self) -> None:
        if self.is_first_step:
            return
        self.current_step -= 1
        self._show_current_page()
        self.on_step_change()

    def draft(self) -> ProfileDraft:
        return self.state.draft(self.permissions_page.allowed_roots())

    def take_key_secret(self) -> OneShotSecretSource:
        return self.state.take_key_secret()

    def summary(self, draft: ProfileDraft) -> str:
        return profile_confirmation_text(draft)

    def _fields_changed(self) -> None:
        self.connection_page.refresh()
        self.authentication_page.refresh()
        self.permissions_page.refresh()

    def _show_current_page(self) -> None:
        for index, page in enumerate(self.pages):
            if index == self.current_step:
                page.grid()
                page.tkraise()
            else:
                page.grid_remove()
