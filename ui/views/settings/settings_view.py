"""Экран настроек: вкладки-подразделы."""

from __future__ import annotations

import customtkinter as ctk

from ui.components.section_tabs import SectionTabs
from ui.fonts import get_font
from ui.views.base_view import BaseView
from ui.views.settings.tabs.about_tab import AboutTab
from ui.views.settings.tabs.backups_tab import BackupsTab
from ui.views.settings.tabs.general_tab import GeneralTab
from ui.views.settings.tabs.notifications_tab import (
    NotificationsTab,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_TITLE_FONT_SIZE = 22
_PAGE_PADX = 24
_PAGE_PADY_TOP = 20


class SettingsView(BaseView):
    """Экран настроек с вкладками."""

    DEFAULT_TAB = "general"

    def __init__(self, master, window):
        super().__init__(master, window)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_tabs()

    # --- Публичное ---

    def on_show(self) -> None:
        current = self.tabs.current or self.DEFAULT_TAB
        self.tabs.show(current)

    def show_tab(self, key: str) -> None:
        self.tabs.show(key)

    # --- Построение ---

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(
            row=0, column=0, sticky="ew",
            padx=_PAGE_PADX, pady=(_PAGE_PADY_TOP, 12),
        )
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Настройки",
            anchor="w",
            font=get_font(_TITLE_FONT_SIZE, "bold"),
        ).grid(row=0, column=0, sticky="w")

    def _build_tabs(self) -> None:
        self.tabs = SectionTabs(self)
        self.tabs.grid(
            row=1, column=0, sticky="nsew",
            padx=_PAGE_PADX, pady=(0, 20),
        )

        container = self.tabs.container
        window = self.window

        self.tabs.add_tab(
            "general", "Общие",
            lambda: GeneralTab(container, window=window),
        )
        self.tabs.add_tab(
            "notifications", "Уведомления",
            lambda: NotificationsTab(container, window=window),
        )
        self.tabs.add_tab(
            "backups", "Бэкапы",
            lambda: BackupsTab(container, window=window),
        )
        self.tabs.add_tab(
            "about", "Описание",
            lambda: AboutTab(container, window=window),
        )

        self.tabs.show(self.DEFAULT_TAB)
