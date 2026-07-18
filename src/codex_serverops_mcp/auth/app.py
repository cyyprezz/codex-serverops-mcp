from __future__ import annotations

import argparse
import os
import sys
import time
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from codex_serverops_mcp.ssh.prompts import PromptKind

from .askpass import is_askpass_invocation, run_askpass
from .client import DirectAuthClient
from .launcher import AUTH_TOKEN_ENVIRONMENT
from .model import AuthPrompt

KIND_LABELS = {
    PromptKind.HOST_KEY: "SSH-Hostschlüssel bestätigen",
    PromptKind.PASSWORD: "SSH-Passwort eingeben",
    PromptKind.KEY_PASSPHRASE: "Schlüssel-Passphrase eingeben",
    PromptKind.SUDO_PASSWORD: "sudo-Passwort eingeben",
}


class AuthWindow:
    def __init__(self, client: DirectAuthClient, prompt: AuthPrompt) -> None:
        self.client = client
        self.prompt = prompt
        self.exit_code = 2
        self.root = tk.Tk()
        self.root.title("ServerOps – lokale Authentifizierung")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build()
        remaining_ms = max(1, round((prompt.expires_at - time.time()) * 1_000))
        self.root.after(remaining_ms, self._timeout)
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(750, lambda: self.root.attributes("-topmost", False))

    def run(self) -> int:
        self.root.mainloop()
        return self.exit_code

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text=KIND_LABELS[self.prompt.kind], font=("Segoe UI", 13, "bold")).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 12),
        )
        target = self.prompt.target
        details = (
            f"Profil: {target.display_name} ({target.profile_name})\n"
            f"Ziel: {target.user}@{target.host}:{target.port}"
        )
        ttk.Label(frame, text=details, justify="left").grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
        )
        ttk.Label(
            frame,
            text=self.prompt.prompt,
            wraplength=520,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 12))
        if self.prompt.kind is PromptKind.HOST_KEY:
            ttk.Button(frame, text="Ablehnen", command=self._reject).grid(
                row=3,
                column=0,
                sticky="w",
            )
            ttk.Button(frame, text="Vertrauen und verbinden", command=self._confirm).grid(
                row=3,
                column=1,
                sticky="e",
            )
        else:
            self.entry = ttk.Entry(frame, width=54, show="●")
            self.entry.grid(row=3, column=0, columnspan=2, sticky="ew")
            self.entry.bind("<Return>", lambda _event: self._submit())
            self.entry.focus_set()
            ttk.Button(frame, text="Abbrechen", command=self._cancel).grid(
                row=4,
                column=0,
                sticky="w",
                pady=(12, 0),
            )
            ttk.Button(frame, text="Sicher übermitteln", command=self._submit).grid(
                row=4,
                column=1,
                sticky="e",
                pady=(12, 0),
            )
        ttk.Label(
            frame,
            text="Die Eingabe wird direkt an den lokalen Session-Worker übertragen.",
            foreground="#555555",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(14, 0))

    def _submit(self) -> None:
        text = self.entry.get()
        self.entry.delete(0, tk.END)
        response = bytearray(text.encode("utf-8"))
        text = ""
        try:
            self.client.submit_secret(response)
        except Exception:
            self._show_failure()
            return
        self.exit_code = 0
        self.root.destroy()

    def _confirm(self) -> None:
        self._send_decision(self.client.confirm, exit_code=0)

    def _reject(self) -> None:
        self._send_decision(self.client.reject, exit_code=2)

    def _cancel(self) -> None:
        self._send_decision(self.client.cancel, exit_code=2, show_failure=False)

    def _timeout(self) -> None:
        self._send_decision(self.client.report_timeout, exit_code=3, show_failure=False)

    def _send_decision(
        self,
        action: Callable[[], str],
        *,
        exit_code: int,
        show_failure: bool = True,
    ) -> None:
        try:
            action()
        except Exception:
            if show_failure:
                self._show_failure()
            else:
                self.client.close()
                self.root.destroy()
            return
        self.exit_code = exit_code
        self.root.destroy()

    def _show_failure(self) -> None:
        messagebox.showerror(
            "ServerOps",
            "Die Antwort konnte nicht sicher an den Session-Worker übertragen werden.",
            parent=self.root,
        )
        self.client.close()
        self.exit_code = 3
        self.root.destroy()


def run_auth_app(pipe: str, request_id: str) -> int:
    token = os.environ.pop(AUTH_TOKEN_ENVIRONMENT, "")
    if not token:
        return 3
    client = DirectAuthClient(pipe, request_id, token)
    try:
        prompt = client.open()
    except Exception:
        client.close()
        return 3
    return AuthWindow(client, prompt).run()


def main() -> None:
    if is_askpass_invocation():
        raise SystemExit(run_askpass(sys.argv[1:]))
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()
    raise SystemExit(run_auth_app(args.pipe, args.request_id))


if __name__ == "__main__":
    main()
