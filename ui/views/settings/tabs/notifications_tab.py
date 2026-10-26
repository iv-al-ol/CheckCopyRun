"""Вкладка «Уведомления»: каналы, автозакрытие.

Мастер-чекбокс «Включить уведомления» стоит отдельно, над
рамкой: он управляет группой, но сам в неё не входит.
Все зависимые параметры собраны в **одну** рамку с тонкой
границей (`SURFACE_BORDER`), у каждого — короткое пояснение.

Строки с полем ввода (автозакрытие) — отдельные
горизонтальные фреймы внутри рамки: поле прижато к тексту
своего параметра, а не выравнивается по соседям через grid.
Примечание под параметром растягивается на всю ширину.

При снятии мастер-галочки всё содержимое рамки блокируется,
а подписи гаснут по цвету.
"""

from __future__ import annotations

import customtkinter as ctk

from config.constants import (
    NOTIFY_AUTO_CLOSE_MAX,
    NOTIFY_AUTO_CLOSE_MIN,
)
from ui.components.hint_label import HintLabel
from ui.fonts import get_font
from ui.palette import SURFACE_BORDER, SURFACE_RADIUS
from ui.views.settings.tabs.base_tab import SettingsTab
from utils.logger import get_logger

logger = get_logger(__name__)

_SECTION_FONT_SIZE = 14

_ENTRY_WIDTH = 60
_SECTION_PADY_TOP = 8

# Горизонтальный отступ параметров внутри рамки. Совпадает с
# отступом примечаний (`HintLabel`), чтобы текст начинался под
# чекбоксом.
_ITEM_PADX = 4

_GROUP_BORDER_WIDTH = 1
_GROUP_PADX = 14
# Внутри рамки верхний зазор даёт сам первый параметр
# (`HintLabel.item_pady()`), поэтому здесь только небольшой
# отступ от границы.
_GROUP_PADY_V = 4
_GROUP_PADDING_BOTTOM = 16

_ENABLED_TEXT_COLOR = ("gray10", "gray90")
_DISABLED_TEXT_COLOR = ("gray55", "gray45")


class NotificationsTab(SettingsTab):
    """Настройки уведомлений об изменениях в источнике."""

    def __init__(self, master, window, **kwargs):
        super().__init__(master, window, **kwargs)
        self._group_widgets: list = []
        self._group_labels: list[ctk.CTkLabel] = []
        self._group_hints: list[HintLabel] = []
        self._inner = None
        self._build()
        self._sync_from_settings()

    # --- Построение ---

    def _build(self) -> None:
        ctk.CTkLabel(
            self,
            text="Уведомления",
            anchor="w",
            font=get_font(_SECTION_FONT_SIZE, "bold"),
        ).grid(
            row=0, column=0, sticky="w",
            padx=4, pady=(_SECTION_PADY_TOP, 8),
        )

        # --- Мастер-выключатель (вне рамки) ---
        self._enabled_var = ctk.BooleanVar(value=True)
        self._enabled_cb = ctk.CTkCheckBox(
            self,
            text="Включить уведомления",
            variable=self._enabled_var,
            command=self._on_enabled_toggle,
        )
        self._enabled_cb.grid(
            row=1, column=0, sticky="w",
            padx=_ITEM_PADX, pady=(0, _GROUP_PADDING_BOTTOM),
        )

        group = ctk.CTkFrame(
            self,
            fg_color="transparent",
            border_width=_GROUP_BORDER_WIDTH,
            border_color=SURFACE_BORDER,
            corner_radius=SURFACE_RADIUS,
        )
        group.grid(
            row=2, column=0, sticky="ew",
            padx=4, pady=(0, _GROUP_PADDING_BOTTOM),
        )
        group.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(group, fg_color="transparent")
        inner.grid(
            row=0, column=0, sticky="ew",
            padx=_GROUP_PADX, pady=_GROUP_PADY_V,
        )
        inner.grid_columnconfigure(0, weight=1)
        self._inner = inner

        row = 0

        # --- Каналы ---
        self._changes_var = ctk.BooleanVar(value=True)
        self._changes_cb = self._track(ctk.CTkCheckBox(
            inner,
            text="Сообщать об изменениях файлов в источнике",
            variable=self._changes_var,
            command=self._on_changes_toggle,
        ))
        self._changes_cb.grid(
            row=row, column=0, sticky="w",
            padx=_ITEM_PADX, pady=HintLabel.item_pady(),
        )
        row += 1
        self._hint(
            row,
            "При любом изменении в папке источника придёт "
            "уведомление с количеством изменений.",
        )
        row += 1

        self._message_var = ctk.BooleanVar(value=True)
        self._message_cb = self._track(ctk.CTkCheckBox(
            inner,
            text="Сообщать о письме из !CCRun/message.txt",
            variable=self._message_var,
            command=self._on_message_toggle,
        ))
        self._message_cb.grid(
            row=row, column=0, sticky="w",
            padx=_ITEM_PADX, pady=HintLabel.item_pady(),
        )
        row += 1
        self._hint(
            row,
            "Автор папки источника может оставить текст в этом "
            "файле — он покажется в уведомлении. В целевую папку "
            "файл не копируется.",
        )
        row += 1

        self._aggregate_var = ctk.BooleanVar(value=False)
        self._aggregate_cb = self._track(ctk.CTkCheckBox(
            inner,
            text="Объединять изменения нескольких профилей",
            variable=self._aggregate_var,
            command=self._on_aggregate_toggle,
        ))
        self._aggregate_cb.grid(
            row=row, column=0, sticky="w",
            padx=_ITEM_PADX, pady=HintLabel.item_pady(),
        )
        row += 1
        self._hint(
            row,
            "По всем профилям будет приходить одно общее уведомление.",
        )
        row += 1

        # --- Автозакрытие: одна горизонтальная строка ---
        auto_row = ctk.CTkFrame(inner, fg_color="transparent")
        auto_row.grid(
            row=row, column=0, sticky="w",
            padx=_ITEM_PADX, pady=HintLabel.item_pady(),
        )

        self._add_label(auto_row, "Скрывать через").pack(side="left")

        self._auto_close_entry = ctk.CTkEntry(
            auto_row, width=_ENTRY_WIDTH,
        )
        self._auto_close_entry.pack(side="left", padx=(8, 6))
        self._auto_close_entry.bind(
            "<Return>", self._on_auto_close_commit,
        )
        self._auto_close_entry.bind(
            "<FocusOut>", self._on_auto_close_commit,
        )

        self._add_label(auto_row, "сек.").pack(side="left")
        row += 1

        self._hint(
            row,
            f"0 — уведомление остаётся до клика по нему. "
            f"Максимум — {NOTIFY_AUTO_CLOSE_MAX} секунд.",
        )

    def _hint(self, row: int, text: str) -> None:
        """Примечание под параметром, во всю ширину колонки."""
        hint = HintLabel(self._inner, text=text)
        hint.place_in_grid(row=row)
        self._group_hints.append(hint)

    def _add_label(self, master, text: str) -> ctk.CTkLabel:
        """Подпись параметра, гаснущая вместе с блокировкой."""
        label = ctk.CTkLabel(
            master, text=text, anchor="w",
            text_color=_ENABLED_TEXT_COLOR,
        )
        self._group_labels.append(label)
        return label

    def _track(self, widget):
        """Регистрирует виджет для блокировки вместе с группой."""
        self._group_widgets.append(widget)
        return widget

    # --- Синхронизация ---

    def _sync_from_settings(self) -> None:
        s = self.window.settings
        self._enabled_var.set(bool(s.notifications_enabled))
        self._changes_var.set(bool(s.notify_source_changes))
        self._message_var.set(bool(s.notify_message))
        self._aggregate_var.set(bool(s.notify_aggregate))

        self._auto_close_entry.delete(0, "end")
        self._auto_close_entry.insert(
            0, str(s.notify_auto_close_sec),
        )

        self._apply_enabled_state()

    def on_show(self) -> None:
        self._sync_from_settings()

    def _apply_enabled_state(self) -> None:
        enabled = bool(self._enabled_var.get())
        state = "normal" if enabled else "disabled"

        for widget in self._group_widgets:
            widget.configure(state=state)

        self._auto_close_entry.configure(state=state)

        label_color = (
            _ENABLED_TEXT_COLOR if enabled
            else _DISABLED_TEXT_COLOR
        )
        for label in self._group_labels:
            label.configure(text_color=label_color)

        for hint in self._group_hints:
            hint.set_enabled(enabled)

    # --- Обработчики ---

    def _on_enabled_toggle(self) -> None:
        enabled = bool(self._enabled_var.get())
        self.window.settings.notifications_enabled = enabled
        self._apply_enabled_state()
        self.window.save_settings_now()
        state = "включены" if enabled else "выключены"
        self.window.set_status(f"Уведомления {state}")

    def _on_changes_toggle(self) -> None:
        enabled = bool(self._changes_var.get())
        self.window.settings.notify_source_changes = enabled
        self.window.save_settings_now()
        state = "включены" if enabled else "выключены"
        self.window.set_status(
            f"Уведомления об изменениях файлов {state}",
        )

    def _on_message_toggle(self) -> None:
        enabled = bool(self._message_var.get())
        self.window.settings.notify_message = enabled
        self.window.save_settings_now()
        state = "включены" if enabled else "выключены"
        self.window.set_status(
            f"Уведомления о сообщении источника {state}",
        )

    def _on_aggregate_toggle(self) -> None:
        enabled = bool(self._aggregate_var.get())
        self.window.settings.notify_aggregate = enabled
        self.window.save_settings_now()
        state = "включено" if enabled else "выключено"
        self.window.set_status(f"Объединение уведомлений {state}")

    def _on_auto_close_commit(self, _event=None) -> None:
        raw = self._auto_close_entry.get().strip()
        try:
            value = int(raw)
        except ValueError:
            self._restore_auto_close()
            self.window.set_status(
                "Автозакрытие: нужно целое число секунд",
            )
            return

        clamped = max(
            NOTIFY_AUTO_CLOSE_MIN,
            min(NOTIFY_AUTO_CLOSE_MAX, value),
        )
        self.window.settings.notify_auto_close_sec = clamped
        self._restore_auto_close()
        self.window.save_settings_now()
        if clamped == 0:
            self.window.set_status(
                "Уведомления не закрываются автоматически",
            )
            return
        self.window.set_status(
            f"Уведомления скрываются через {clamped} с",
        )

    def _restore_auto_close(self) -> None:
        value = self.window.settings.notify_auto_close_sec
        self._auto_close_entry.delete(0, "end")
        self._auto_close_entry.insert(0, str(value))
