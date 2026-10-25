"""Форма профиля: поля ввода, чекбоксы.

Кнопки действий (Копировать / Запустить приложение / Резервные
копии) находятся в ProfileView, не в форме — они привязаны к
низу окна, не входят в прокручиваемую область.

Чекбокс «Запускать приложение после копирования» неактивен,
пока не выбрано запускаемое приложение.
"""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from ui.components.button import VARIANT_SECONDARY, StyledButton
from ui.components.hint_label import HintLabel
from ui.fonts import get_font

_LABEL_FONT_SIZE = 13
_ENTRY_HEIGHT = 32
_BROWSE_WIDTH = 110


class _PathRow(ctk.CTkFrame):
    """Строка: label + entry + кнопка выбора (+ опционально «Открыть»)."""

    def __init__(
        self,
        master,
        *,
        label: str,
        pick_text: str,
        on_pick: Callable[[], None],
        on_open: Callable[[], None] | None = None,
        top_pad: int = 0,
    ):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)

        columns = 3 if on_open is not None else 2

        ctk.CTkLabel(
            self,
            text=label,
            anchor="w",
            font=get_font(_LABEL_FONT_SIZE, "bold"),
        ).grid(
            row=0, column=0, columnspan=columns,
            sticky="w", pady=(top_pad, 4),
        )

        self._entry = ctk.CTkEntry(
            self, height=_ENTRY_HEIGHT, state="readonly",
        )
        self._entry.grid(
            row=1, column=0, sticky="ew",
            padx=(0, 8),
        )

        StyledButton(
            self, text=pick_text,
            variant=VARIANT_SECONDARY, width=_BROWSE_WIDTH,
            command=on_pick,
        ).grid(
            row=1, column=1, sticky="e",
            padx=(0, 8) if on_open is not None else 0,
        )

        self._open_btn: StyledButton | None = None
        if on_open is not None:
            self._open_btn = StyledButton(
                self, text="Открыть папку",
                variant=VARIANT_SECONDARY, width=_BROWSE_WIDTH,
                command=on_open,
            )
            self._open_btn.grid(row=1, column=2, sticky="e")
            self._open_btn.configure(state="disabled")

    def set_value(self, value: str) -> None:
        self._entry.configure(state="normal")
        self._entry.delete(0, "end")
        if value:
            self._entry.insert(0, value)
        self._entry.configure(state="readonly")

    def set_open_enabled(self, enabled: bool) -> None:
        if self._open_btn is not None:
            self._open_btn.configure(
                state="normal" if enabled else "disabled",
            )


class ProfileForm(ctk.CTkFrame):
    """Форма профиля: поля и чекбоксы без кнопок действий."""

    def __init__(
        self,
        master,
        *,
        on_pick_source: Callable[[], None],
        on_open_source: Callable[[], None],
        on_pick_destination: Callable[[], None],
        on_open_destination: Callable[[], None],
        on_pick_exe: Callable[[], None],
        on_backup_toggle: Callable[[], None],
        on_run_after_toggle: Callable[[], None],
        on_check_on_startup_toggle: Callable[[], None],
        on_mirror_toggle: Callable[[], None],
        on_notify_changes_toggle: Callable[[], None],
        on_notify_message_toggle: Callable[[], None],
    ):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)

        self._source_row = _PathRow(
            self,
            label="Копировать из:",
            pick_text="Выбрать директорию",
            on_pick=on_pick_source,
            on_open=on_open_source,
        )
        self._source_row.grid(row=0, column=0, sticky="ew")

        self._dest_row = _PathRow(
            self,
            label="Копировать в:",
            pick_text="Выбрать директорию",
            on_pick=on_pick_destination,
            on_open=on_open_destination,
            top_pad=12,
        )
        self._dest_row.grid(row=1, column=0, sticky="ew")

        self._exe_row = _PathRow(
            self,
            label="Запускаемое приложение:",
            pick_text="Выбрать файл",
            on_pick=on_pick_exe,
            top_pad=12,
        )
        self._exe_row.grid(row=2, column=0, sticky="ew")

        # Ритм отступов: у каждого параметра без примечания
        # нижний отступ равен нижнему отступу примечания. У
        # параметра с примечанием он нулевой — зазор даёт само
        # примечание. Так интервалы одинаковы во всех формах.
        self._backup_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self,
            text="Создавать резервную копию изменённых файлов",
            variable=self._backup_var,
            command=on_backup_toggle,
        ).grid(
            row=3, column=0, sticky="w",
            pady=HintLabel.item_pady_plain(),
        )

        self._run_after_var = ctk.BooleanVar(value=False)
        self._run_after_cb = ctk.CTkCheckBox(
            self,
            text="Запускать приложение после копирования",
            variable=self._run_after_var,
            command=on_run_after_toggle,
        )
        self._run_after_cb.grid(
            row=4, column=0, sticky="w",
            pady=HintLabel.item_pady_plain(),
        )

        self._check_on_startup_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self,
            text="Проверять директорию при запуске CheckCopyRun",
            variable=self._check_on_startup_var,
            command=on_check_on_startup_toggle,
        ).grid(
            row=5, column=0, sticky="w",
            pady=HintLabel.item_pady_plain(),
        )

        self._mirror_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self,
            text="Режим зеркала",
            variable=self._mirror_var,
            command=on_mirror_toggle,
        ).grid(
            row=6, column=0, sticky="w",
            pady=HintLabel.item_pady(),
        )

        HintLabel(
            self,
            text=(
                "Файлы и папки, которых нет в папке источника, "
                "будут убраны из папки."
            ),
        ).place_in_grid(row=7, padx=0)

        self._notify_changes_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self,
            text="Уведомлять об изменениях файлов этого источника",
            variable=self._notify_changes_var,
            command=on_notify_changes_toggle,
        ).grid(
            row=8, column=0, sticky="w",
            pady=HintLabel.item_pady_plain(),
        )

        self._notify_message_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self,
            text="Уведомлять о сообщении из !CCRun/message.txt",
            variable=self._notify_message_var,
            command=on_notify_message_toggle,
        ).grid(
            row=9, column=0, sticky="w",
            pady=HintLabel.item_pady(),
        )

        HintLabel(
            self,
            text=(
                "Файл составляется автором папки источника. "
                "Файл не копируется в целевую папку."
            ),
        ).place_in_grid(row=10, padx=0)

    # --- Свойства чекбоксов ---

    @property
    def create_backup(self) -> bool:
        return bool(self._backup_var.get())

    @property
    def run_after_copy(self) -> bool:
        return bool(self._run_after_var.get())

    @property
    def check_on_startup(self) -> bool:
        return bool(self._check_on_startup_var.get())

    @property
    def mirror_mode(self) -> bool:
        return bool(self._mirror_var.get())

    @property
    def notify_on_changes(self) -> bool:
        return bool(self._notify_changes_var.get())

    @property
    def notify_on_message(self) -> bool:
        return bool(self._notify_message_var.get())

    # --- Обновление ---

    def set_create_backup(self, value: bool) -> None:
        """Программно изменить чекбокс (без вызова command)."""
        self._backup_var.set(bool(value))

    def update_values(
        self,
        *,
        source: str,
        destination: str,
        exe_name: str,
        create_backup: bool,
        run_after_copy: bool,
        check_on_startup: bool,
        mirror_mode: bool,
        notify_on_changes: bool = True,
        notify_on_message: bool = True,
    ) -> None:
        self._source_row.set_value(source)
        self._dest_row.set_value(destination)
        self._exe_row.set_value(exe_name)
        self._backup_var.set(create_backup)
        self._check_on_startup_var.set(check_on_startup)
        self._mirror_var.set(mirror_mode)
        self._notify_changes_var.set(notify_on_changes)
        self._notify_message_var.set(notify_on_message)

        has_exe = bool(exe_name)
        if has_exe:
            self._run_after_var.set(run_after_copy)
            self._run_after_cb.configure(state="normal")
        else:
            self._run_after_var.set(False)
            self._run_after_cb.configure(state="disabled")

    def update_open_buttons(
        self, *, source_enabled: bool, destination_enabled: bool,
    ) -> None:
        self._source_row.set_open_enabled(source_enabled)
        self._dest_row.set_open_enabled(destination_enabled)
