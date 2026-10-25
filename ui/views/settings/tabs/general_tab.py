"""Вкладка «Общие»: тема, система, поведение."""

from __future__ import annotations

import customtkinter as ctk

from config.constants import THEME_DEFAULT
from services.system import autostart
from ui.components.hint_label import HintLabel
from ui.components.option_menu import StyledOptionMenu
from ui.fonts import get_font
from ui.themes import THEME_LABELS, apply_theme
from ui.views.settings.tabs.base_tab import SettingsTab
from utils.logger import get_logger

logger = get_logger(__name__)

_SECTION_FONT_SIZE = 14
_BODY_FONT_SIZE = 13

_OPTION_MENU_WIDTH = 220

_SECTION_PADY_TOP = 8


class GeneralTab(SettingsTab):
    """Общие настройки: внешний вид и поведение."""

    def __init__(self, master, window, **kwargs):
        super().__init__(master, window, **kwargs)
        self._build()
        self._sync_from_settings()

    # --- Построение ---

    def _build(self) -> None:
        row = 0

        # --- "Внешний вид" ---
        row = self._add_section_title(row, "Внешний вид")

        theme_row = ctk.CTkFrame(self, fg_color="transparent")
        theme_row.grid(
            row=row, column=0, sticky="w",
            padx=4, pady=HintLabel.item_pady_plain(),
        )
        row += 1

        ctk.CTkLabel(
            theme_row, text="Тема:", anchor="w",
            font=get_font(_BODY_FONT_SIZE),
        ).pack(side="left", padx=(0, 12))

        self._theme_var = ctk.StringVar(
            value=THEME_LABELS.get(THEME_DEFAULT, "Системная"),
        )
        StyledOptionMenu(
            theme_row,
            values=list(THEME_LABELS.values()),
            variable=self._theme_var,
            command=self._on_theme_change,
            width=_OPTION_MENU_WIDTH,
        ).pack(side="left")

        # --- "Система" ---
        row = self._add_section_title(row, "Система")

        self._autostart_var = ctk.BooleanVar(value=False)
        self._autostart_cb = ctk.CTkCheckBox(
            self,
            text="Запускать при старте Windows",
            variable=self._autostart_var,
            command=self._on_autostart_toggle,
        )
        self._autostart_cb.grid(
            row=row, column=0, sticky="w",
            padx=4, pady=HintLabel.item_pady_plain(),
        )
        row += 1

        self._start_minimized_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self,
            text="Запускать свернутым",
            variable=self._start_minimized_var,
            command=self._on_start_minimized_toggle,
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=HintLabel.item_pady_plain(),
        )
        row += 1

        self._minimize_to_tray_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self,
            text="Сворачивать в системный трей при закрытии",
            variable=self._minimize_to_tray_var,
            command=self._on_minimize_to_tray_toggle,
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=HintLabel.item_pady_plain(),
        )
        row += 1

        self._confirm_exit_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self,
            text="Спрашивать подтверждение при закрытии",
            variable=self._confirm_exit_var,
            command=self._on_confirm_exit_toggle,
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=HintLabel.item_pady_plain(),
        )
        row += 1

        # --- "Поведение" ---
        row = self._add_section_title(row, "Поведение")

        self._hash_cache_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self,
            text="Использовать кэш хэшей при сравнении файлов",
            variable=self._hash_cache_var,
            command=self._on_hash_cache_toggle,
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=HintLabel.item_pady(),
        )
        row += 1

        HintLabel(
            self,
            text=(
                "Ускоряет повторные копирования: файлы сравниваются "
                "по размеру и времени изменения, хэш пересчитывается "
                "только при изменениях. Отключите, если нужна "
                "побайтовая сверка при каждом запуске."
            ),
        ).place_in_grid(row=row)
        row += 1

        self._autocheck_restored_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self,
            text=(
                "Выполнять автопроверку для профилей, "
                "где восстановлен бэкап"
            ),
            variable=self._autocheck_restored_var,
            command=self._on_autocheck_restored_toggle,
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=HintLabel.item_pady(),
        )
        row += 1

        HintLabel(
            self,
            text=(
                "Если профиль восстановлен из резервной копии, "
                "при запуске приложения автопроверка для него "
                "пропускается — это защищает восстановленные "
                "файлы от перезаписи новыми из источника. "
                "Ручное копирование (кнопка «Копировать» или ▶) "
                "работает всегда. Включите, если хотите, чтобы "
                "автопроверка выполнялась и для таких профилей."
            ),
        ).place_in_grid(row=row)

    def _add_section_title(self, row: int, title: str) -> int:
        ctk.CTkLabel(
            self,
            text=title,
            anchor="w",
            font=get_font(_SECTION_FONT_SIZE, "bold"),
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=(_SECTION_PADY_TOP, 8),
        )
        return row + 1

    # --- Синхронизация ---

    def _sync_from_settings(self) -> None:
        s = self.window.settings
        self._theme_var.set(
            THEME_LABELS.get(s.theme, THEME_LABELS["system"]),
        )
        self._confirm_exit_var.set(bool(s.confirm_on_exit))
        self._minimize_to_tray_var.set(bool(s.minimize_to_tray))
        self._autostart_var.set(bool(s.autostart))
        self._start_minimized_var.set(bool(s.start_minimized))
        self._hash_cache_var.set(bool(s.hash_cache_enabled))
        self._autocheck_restored_var.set(
            bool(s.run_autocheck_on_restored)
        )

        if not autostart.is_supported():
            self._autostart_cb.configure(state="disabled")

    def on_show(self) -> None:
        self._sync_from_settings()

    # --- Обработчики ---

    def _on_theme_change(self, label: str) -> None:
        key = _label_to_theme_key(label)
        if key is None:
            logger.warning("Неизвестная тема: %r", label)
            return

        self.window.settings.theme = key
        apply_theme(key)
        self.window.save_settings_now()
        self.window.set_status(f"Тема изменена: {label}")

    def _on_confirm_exit_toggle(self) -> None:
        enabled = bool(self._confirm_exit_var.get())
        self.window.settings.confirm_on_exit = enabled
        self.window.save_settings_now()
        state = "включено" if enabled else "выключено"
        self.window.set_status(f"Подтверждение выхода {state}")

    def _on_minimize_to_tray_toggle(self) -> None:
        enabled = bool(self._minimize_to_tray_var.get())
        self.window.settings.minimize_to_tray = enabled
        self.window.save_settings_now()
        state = "включено" if enabled else "выключено"
        self.window.set_status(f"Сворачивание в трей {state}")

    def _on_autostart_toggle(self) -> None:
        enabled = bool(self._autostart_var.get())
        success = autostart.set_enabled(enabled)

        if success:
            self.window.settings.autostart = enabled
            self.window.save_settings_now()
            state = "включён" if enabled else "выключен"
            self.window.set_status(f"Автозапуск {state}")
        else:
            self._autostart_var.set(not enabled)
            self.window.set_status("Ошибка настройки автозапуска")

    def _on_start_minimized_toggle(self) -> None:
        enabled = bool(self._start_minimized_var.get())
        self.window.settings.start_minimized = enabled
        self.window.save_settings_now()
        state = "включён" if enabled else "выключен"
        self.window.set_status(f"Запуск свернутым {state}")

    def _on_hash_cache_toggle(self) -> None:
        enabled = bool(self._hash_cache_var.get())
        self.window.settings.hash_cache_enabled = enabled
        self.window.save_settings_now()
        state = "включён" if enabled else "выключен"
        self.window.set_status(f"Кэш хэшей {state}")

    def _on_autocheck_restored_toggle(self) -> None:
        enabled = bool(self._autocheck_restored_var.get())
        self.window.settings.run_autocheck_on_restored = enabled
        self.window.save_settings_now()
        state = "включена" if enabled else "выключена"
        self.window.set_status(
            f"Автопроверка для восстановленных профилей {state}",
        )


def _label_to_theme_key(label: str) -> str | None:
    for key, text in THEME_LABELS.items():
        if text == label:
            return key
    return None
