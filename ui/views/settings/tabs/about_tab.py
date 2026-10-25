"""Вкладка «Описание»: название, версия, краткая информация."""

from __future__ import annotations

import customtkinter as ctk

from config.constants import APP_NAME, APP_TITLE, APP_VERSION
from ui.components.hint_label import HintLabel
from ui.fonts import get_font
from ui.views.settings.tabs.base_tab import SettingsTab

_NAME_FONT_SIZE = 18
_VERSION_FONT_SIZE = 13

_SECTION_PADY_TOP = 8


class AboutTab(SettingsTab):
    """Информация о приложении."""

    def __init__(self, master, window, **kwargs):
        super().__init__(master, window, **kwargs)
        self._build()

    def _build(self) -> None:
        row = 0

        ctk.CTkLabel(
            self,
            text=APP_NAME,
            anchor="w",
            font=get_font(_NAME_FONT_SIZE, "bold"),
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=(_SECTION_PADY_TOP, 2),
        )
        row += 1

        ctk.CTkLabel(
            self,
            text=f"Версия {APP_VERSION}",
            anchor="w",
            text_color=("gray40", "gray60"),
            font=get_font(_VERSION_FONT_SIZE),
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=(0, 16),
        )
        row += 1

        ctk.CTkLabel(
            self,
            text=APP_TITLE,
            anchor="w",
            font=get_font(_VERSION_FONT_SIZE, "bold"),
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=(0, 4),
        )
        row += 1

        HintLabel(
            self,
            text=(
                "Утилита для проверки папки с приложением, "
                "копирования изменений и запуска соответствующего "
                "приложения."
            ),
        ).place_in_grid(row=row)
        row += 1

        HintLabel(
            self,
            text=(
                "Настройки хранятся в папке «Документы» (файл "
                "зашифрован через DPAPI). Логи — в той же папке, "
                "подпапка log."
            ),
        ).place_in_grid(row=row)
