from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableFormHost(ttk.Frame):
    """Keep wizard navigation visible while allowing tall pages to scroll."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self._window_id: int | None = None
        self.canvas.bind("<Configure>", self._resize_content)
        self.winfo_toplevel().bind("<MouseWheel>", self._scroll, add="+")

    def attach(self, content: ttk.Frame) -> None:
        self._window_id = self.canvas.create_window(
            (0, 0),
            window=content,
            anchor="nw",
        )
        content.bind("<Configure>", self._update_scroll_region, add="+")
        self.after_idle(self._update_scroll_region)

    def scroll_to_top(self) -> None:
        self.after_idle(lambda: self.canvas.yview_moveto(0.0))

    def _resize_content(self, event: tk.Event[tk.Misc]) -> None:
        if self._window_id is not None:
            self.canvas.itemconfigure(self._window_id, width=event.width)

    def _update_scroll_region(self, _event: object | None = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            self.scrollbar.grid_remove()
        else:
            self.scrollbar.grid()

    def _scroll(self, event: tk.Event[tk.Misc]) -> None:
        delta = getattr(event, "delta", 0)
        if delta:
            direction = -1 if delta > 0 else 1
            steps = max(1, abs(delta) // 120)
            self.canvas.yview_scroll(direction * steps, "units")
