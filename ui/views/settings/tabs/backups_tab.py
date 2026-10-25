"""Вкладка «Бэкапы»: политика хранения !Backup_* папок.

Каждая опция — чекбокс + поле ввода + единица в одной строке:
  [✓] Хранить последние     [10] бэкапов
  [✓] Удалять бэкапы старше [30] дней

Политика глобальная, но применяется к destination каждого профиля
отдельно — у каждого свои бэкапы.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.components.hint_label import HintLabel
from ui.fonts import get_font
from ui.views.settings.tabs.base_tab import SettingsTab
from utils.logger import get_logger

logger = get_logger(__name__)

_SECTION_FONT_SIZE = 14
_BODY_FONT_SIZE = 13

_ENTRY_WIDTH = 60
_SECTION_PADY_TOP = 8

# Чекбокс + поле + единица занимают три колонки, четвёртая —
# пустая и растягиваемая. Примечание растягивается на все.
_COLUMNS = 3
_SPACER_COLUMN = 3

_KEEP_LAST_MIN = 1
_KEEP_LAST_MAX = 1000
_DELETE_OLDER_MIN = 1
_DELETE_OLDER_MAX = 3650


class BackupsTab(SettingsTab):
    """Политика хранения бэкапов."""

    def __init__(self, master, window, **kwargs):
        super().__init__(master, window, **kwargs)
        self._build()
        self._sync_from_settings()

    # --- Построение ---

    def _build(self) -> None:
        row = 0
        # Базовый класс растягивает колонку 0; здесь растяжение
        # должно быть у пустой колонки справа, иначе поле ввода
        # отъезжает от своего чекбокса.
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(_SPACER_COLUMN, weight=1)

        # Заголовок секции.
        ctk.CTkLabel(
            self,
            text="Хранение резервных копий",
            anchor="w",
            font=get_font(_SECTION_FONT_SIZE, "bold"),
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=(_SECTION_PADY_TOP, 8),
        )
        row += 1

        # --- «Хранить последние N бэкапов» ---
        # Параметры размещаются прямо в сетке вкладки, без
        # промежуточного фрейма: фрейм добавлял 5 px высоты, и
        # зазор до примечания отличался от других вкладок.
        self._keep_last_var = ctk.BooleanVar(value=False)
        self._keep_last_cb = ctk.CTkCheckBox(
            self,
            text="Хранить последние",
            variable=self._keep_last_var,
            command=self._on_keep_last_toggle,
        )
        self._keep_last_cb.grid(
            row=row, column=0, sticky="w",
            padx=4, pady=HintLabel.item_pady_plain(),
        )

        self._keep_last_entry = ctk.CTkEntry(
            self, width=_ENTRY_WIDTH,
        )
        self._keep_last_entry.grid(
            row=row, column=1, sticky="w", padx=(8, 6),
        )
        self._keep_last_entry.bind(
            "<Return>", self._on_keep_last_commit,
        )
        self._keep_last_entry.bind(
            "<FocusOut>", self._on_keep_last_commit,
        )

        ctk.CTkLabel(
            self, text="бэкапов",
            font=get_font(_BODY_FONT_SIZE),
        ).grid(row=row, column=2, sticky="w")
        row += 1

        # --- «Удалять бэкапы старше X дней» ---
        self._delete_older_var = ctk.BooleanVar(value=False)
        self._delete_older_cb = ctk.CTkCheckBox(
            self,
            text="Удалять бэкапы старше",
            variable=self._delete_older_var,
            command=self._on_delete_older_toggle,
        )
        self._delete_older_cb.grid(
            row=row, column=0, sticky="w",
            padx=4, pady=HintLabel.item_pady_plain(),
        )

        self._delete_older_entry = ctk.CTkEntry(
            self, width=_ENTRY_WIDTH,
        )
        self._delete_older_entry.grid(
            row=row, column=1, sticky="w", padx=(8, 6),
        )
        self._delete_older_entry.bind(
            "<Return>", self._on_delete_older_commit,
        )
        self._delete_older_entry.bind(
            "<FocusOut>", self._on_delete_older_commit,
        )

        ctk.CTkLabel(
            self, text="дней",
            font=get_font(_BODY_FONT_SIZE),
        ).grid(row=row, column=2, sticky="w")
        row += 1

        # --- Справка (растягивается по ширине) ---
        HintLabel(
            self,
            text=(
                "Если включены оба правила — удаление происходит, "
                "если сработало любое из них (что наступит раньше). "
                "Проверка запускается в конце успешного копирования "
                "для папки назначения каждого профиля отдельно. "
                "Ошибки удаления (папка занята, нет прав) пишутся "
                "в лог, копирование не блокируется."
            ),
        ).place_in_grid(
            row=row, columnspan=_SPACER_COLUMN + 1,
        )

    # --- Синхронизация ---

    def _sync_from_settings(self) -> None:
        s = self.window.settings

        self._keep_last_var.set(bool(s.backup_keep_last_enabled))
        self._keep_last_entry.delete(0, "end")
        self._keep_last_entry.insert(0, str(s.backup_keep_last_n))
        self._keep_last_entry.configure(
            state="normal" if s.backup_keep_last_enabled
            else "disabled",
        )

        self._delete_older_var.set(
            bool(s.backup_delete_older_enabled)
        )
        self._delete_older_entry.delete(0, "end")
        self._delete_older_entry.insert(
            0, str(s.backup_delete_older_days),
        )
        self._delete_older_entry.configure(
            state="normal" if s.backup_delete_older_enabled
            else "disabled",
        )

    def on_show(self) -> None:
        self._sync_from_settings()

    # --- Обработчики: «Хранить последние» ---

    def _on_keep_last_toggle(self) -> None:
        enabled = bool(self._keep_last_var.get())
        self.window.settings.backup_keep_last_enabled = enabled
        self._keep_last_entry.configure(
            state="normal" if enabled else "disabled",
        )
        self.window.save_settings_now()
        state = "включено" if enabled else "выключено"
        self.window.set_status(
            f"Хранить последние бэкапы: {state}",
        )

    def _on_keep_last_commit(self, _event=None) -> None:
        raw = self._keep_last_entry.get().strip()
        current = self.window.settings.backup_keep_last_n

        try:
            n = int(raw)
        except ValueError:
            n = current

        n = max(_KEEP_LAST_MIN, min(_KEEP_LAST_MAX, n))

        self._keep_last_entry.delete(0, "end")
        self._keep_last_entry.insert(0, str(n))

        if n == current:
            return

        self.window.settings.backup_keep_last_n = n
        self.window.save_settings_now()
        self.window.set_status(
            f"Хранить последних бэкапов: {n}",
        )

    # --- Обработчики: «Удалять старше» ---

    def _on_delete_older_toggle(self) -> None:
        enabled = bool(self._delete_older_var.get())
        self.window.settings.backup_delete_older_enabled = enabled
        self._delete_older_entry.configure(
            state="normal" if enabled else "disabled",
        )
        self.window.save_settings_now()
        state = "включено" if enabled else "выключено"
        self.window.set_status(
            f"Удалять бэкапы старше: {state}",
        )

    def _on_delete_older_commit(self, _event=None) -> None:
        raw = self._delete_older_entry.get().strip()
        current = self.window.settings.backup_delete_older_days

        try:
            days = int(raw)
        except ValueError:
            days = current

        days = max(
            _DELETE_OLDER_MIN,
            min(_DELETE_OLDER_MAX, days),
        )

        self._delete_older_entry.delete(0, "end")
        self._delete_older_entry.insert(0, str(days))

        if days == current:
            return

        self.window.settings.backup_delete_older_days = days
        self.window.save_settings_now()
        self.window.set_status(
            f"Удалять бэкапы старше: {days} дн.",
        )
