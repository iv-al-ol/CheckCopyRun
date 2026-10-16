"""Временная заглушка для экранов, которых ещё нет."""

from __future__ import annotations

import customtkinter as ctk

from ui.fonts import get_font
from ui.views.base_view import BaseView


class StubView(BaseView):
    def __init__(self, master, window, title: str):
        super().__init__(master, window)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text=title, font=get_font(22, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(20, 12))

        ctk.CTkLabel(
            self,
            text="Раздел в разработке.",
            anchor="w",
            justify="left",
            text_color=("gray40", "gray60"),
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 20))
