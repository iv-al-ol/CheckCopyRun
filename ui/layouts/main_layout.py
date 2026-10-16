"""Каркас окна: сайдбар + контентная область."""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from ui.layouts.sidebar import Sidebar


class MainLayout(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        on_select: Callable[[str], None],
        on_add_profile: Callable[[], None],
        on_run_profile: Callable[[str], None],
        on_profile_context: Callable[[str, int, int], None],
    ):
        super().__init__(master, corner_radius=0, fg_color="transparent")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.sidebar = Sidebar(
            self,
            on_select=on_select,
            on_add_profile=on_add_profile,
            on_run_profile=on_run_profile,
            on_profile_context=on_profile_context,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        self.content = ctk.CTkFrame(
            self, corner_radius=0, fg_color="transparent",
        )
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
