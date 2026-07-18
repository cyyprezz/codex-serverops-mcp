from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def page_heading(parent: ttk.Frame, title: str, description: str) -> int:
    ttk.Label(parent, text=title, style="SetupPageTitle.TLabel").grid(
        row=0,
        column=0,
        sticky="w",
    )
    ttk.Label(
        parent,
        text=description,
        style="SetupHelp.TLabel",
        wraplength=690,
        justify="left",
    ).grid(row=1, column=0, sticky="ew", pady=(4, 20))
    return 2


def entry_field(
    parent: ttk.Frame,
    row: int,
    label: str,
    variable: tk.StringVar,
    help_text: str,
    *,
    disabled: bool = False,
) -> ttk.Entry:
    ttk.Label(parent, text=label, style="SetupField.TLabel").grid(
        row=row,
        column=0,
        sticky="w",
    )
    entry = ttk.Entry(parent, textvariable=variable)
    entry.grid(row=row + 1, column=0, sticky="ew", pady=(4, 2))
    if disabled:
        entry.configure(state="disabled")
    ttk.Label(
        parent,
        text=help_text,
        style="SetupHelp.TLabel",
        wraplength=690,
        justify="left",
    ).grid(row=row + 2, column=0, sticky="w", pady=(0, 14))
    return entry
