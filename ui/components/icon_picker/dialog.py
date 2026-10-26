"""Диалог выбора иконки профиля.

Тонкий tkinter-слой: строит виджеты, рендерит превью, обрабатывает
клики. Вся логика выбора — в IconPickerState.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from config.constants import DEFAULT_PROFILE_ICON
from ui.components.button import (
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.components.icon_picker.state import IconPickerState
from ui.components.image_utils import load_ctk_image
from ui.components.separator import make_separator
from ui.dialogs import (
    bring_to_front,
    center_on_parent,
    setup_dialog,
    show_error,
)
from ui.fonts import get_emoji_font, get_font
from utils.logger import get_logger

logger = get_logger(__name__)

_IMAGE_EXTS = (".png", ".ico", ".jpg", ".jpeg", ".gif", ".bmp")

_DIALOG_WIDTH = 540
_PREVIEW_SIZE = 64
_ACTION_BUTTON_WIDTH = 150
_GRID_COLS = 8

_EMOJI_PALETTE: list[str] = [
    "📁", "📂", "🗂", "📦", "🚀", "⚙", "🔧", "💾",
    "🖥", "🌐", "⭐", "🧩", "🎯", "🎨", "🔨", "🛠",
    "📊", "📈", "📉", "💼", "💻", "🖱", "⌨", "🖨",
    "🗄", "🔒", "🔑", "🧭", "🧪", "⚗", "🔍", "📌",
]


class _IconPickerDialog:
    """Диалог выбора иконки. Логика — в IconPickerState."""

    def __init__(
        self,
        parent,
        state: IconPickerState,
        parent_visible: bool,
    ):
        self._parent = parent
        self._parent_visible = parent_visible
        self._state = state

        self._result: tuple[str, bool] | None = None

        self._build()
        self._refresh_all()

    # --- Публичное ---

    def run(self) -> tuple[str, bool] | None:
        self._dialog.grab_set()
        center_on_parent(self._dialog, self._parent)
        bring_to_front(self._dialog, self._parent_visible)
        self._parent.wait_window(self._dialog)
        return self._result

    # --- Построение ---

    def _build(self) -> None:
        self._dialog = setup_dialog(
            self._parent, "Иконка профиля", self._parent_visible,
        )
        self._dialog.grid_columnconfigure(0, weight=1)

        row = 0

        ctk.CTkLabel(
            self._dialog,
            text="Иконка профиля",
            anchor="center",
            font=get_font(15, "bold"),
        ).grid(row=row, column=0, sticky="ew", padx=24, pady=(20, 12))
        row += 1

        preview_frame = ctk.CTkFrame(
            self._dialog,
            fg_color="transparent",
            width=_PREVIEW_SIZE + 8,
            height=_PREVIEW_SIZE + 8,
        )
        preview_frame.grid(row=row, column=0, pady=(0, 12))
        preview_frame.grid_propagate(False)

        self._emoji_preview = ctk.CTkLabel(
            preview_frame,
            text=DEFAULT_PROFILE_ICON,
            font=get_emoji_font(36),
            anchor="center",
        )
        self._emoji_preview.place(relx=0.5, rely=0.5, anchor="center")

        self._image_preview = ctk.CTkLabel(
            preview_frame,
            text="",
            anchor="center",
        )
        self._image_ctk = None

        row += 1

        # Палитра эмодзи.
        grid_frame = ctk.CTkFrame(
            self._dialog, fg_color="transparent",
        )
        grid_frame.grid(row=row, column=0, padx=24, pady=(0, 8))
        for i in range(_GRID_COLS):
            grid_frame.grid_columnconfigure(i, weight=1)

        self._emoji_buttons: dict[str, ctk.CTkButton] = {}
        for idx, emoji in enumerate(_EMOJI_PALETTE):
            r = idx // _GRID_COLS
            c = idx % _GRID_COLS
            btn = ctk.CTkButton(
                grid_frame,
                text=emoji,
                width=40,
                height=40,
                corner_radius=6,
                fg_color="transparent",
                hover_color=("gray80", "gray30"),
                text_color=("gray10", "gray90"),
                font=get_emoji_font(18),
                command=lambda e=emoji: self._select_emoji(e),
            )
            btn.grid(row=r, column=c, padx=2, pady=2)
            self._emoji_buttons[emoji] = btn
        row += 1

        row = self._add_separator(row)

        # Чекбокс auto.
        self._auto_var = ctk.BooleanVar(value=False)
        self._auto_checkbox = ctk.CTkCheckBox(
            self._dialog,
            text="Иконка приложения (из exe профиля)",
            variable=self._auto_var,
            command=self._on_auto_toggle,
            onvalue=True,
            offvalue=False,
        )
        self._auto_checkbox.grid(
            row=row, column=0, sticky="ew", padx=24, pady=(0, 4),
        )
        row += 1

        self._auto_hint = ctk.CTkLabel(
            self._dialog,
            text="",
            anchor="w",
            justify="left",
            wraplength=_DIALOG_WIDTH - 48,
            text_color=("gray40", "gray60"),
            font=get_font(11),
        )
        self._auto_hint.grid(
            row=row, column=0, sticky="w", padx=24, pady=(0, 8),
        )
        row += 1

        row = self._add_separator(row)

        # Кнопка выбора другого файла.
        file_row = ctk.CTkFrame(
            self._dialog, fg_color="transparent",
        )
        file_row.grid(row=row, column=0, pady=(0, 8))
        StyledButton(
            file_row,
            text="Выбрать другую иконку",
            variant=VARIANT_SECONDARY,
            width=240,
            command=self._on_pick_file,
        ).pack()
        row += 1

        row = self._add_separator(row)

        # OK / Отмена.
        btns = ctk.CTkFrame(self._dialog, fg_color="transparent")
        btns.grid(row=row, column=0, pady=(4, 20))

        StyledButton(
            btns, text="Сохранить",
            variant=VARIANT_PRIMARY,
            width=_ACTION_BUTTON_WIDTH,
            command=self._on_ok,
        ).pack(side="left", padx=(0, 8))

        StyledButton(
            btns, text="Отмена",
            variant=VARIANT_SECONDARY,
            width=_ACTION_BUTTON_WIDTH,
            command=self._on_cancel,
        ).pack(side="left")

        self._dialog.bind("<Return>", lambda _e: self._on_ok())
        self._dialog.bind("<Escape>", lambda _e: self._on_cancel())
        self._dialog.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Активность чекбокса и подсказка под ним.
        if not self._state.auto_available:
            self._auto_checkbox.configure(state="disabled")
            self._auto_hint.configure(
                text=(
                    "Сначала выберите запускаемое приложение в "
                    "настройках профиля."
                ),
            )
        else:
            exe_path = self._state.exe_path
            if exe_path is None:
                logger.error(
                    "Диалог иконки: auto_available без exe_path",
                )
                self._auto_checkbox.configure(state="disabled")
            else:
                self._auto_hint.configure(
                    text=f"Источник: {exe_path.name}",
                )

    def _add_separator(self, row: int) -> int:
        sep = make_separator(self._dialog)
        sep.grid(
            row=row, column=0, sticky="ew",
            padx=24, pady=(4, 12),
        )
        return row + 1

    # --- Действия ---

    def _select_emoji(self, emoji: str) -> None:
        self._state.select_emoji(emoji)
        self._auto_var.set(False)
        self._refresh_all()

    def _on_pick_file(self) -> None:
        try:
            path = filedialog.askopenfilename(
                parent=self._dialog,
                title="Выберите иконку или exe",
                filetypes=[
                    (
                        "Иконки и программы",
                        "*.png *.ico *.jpg *.jpeg *.gif *.bmp *.exe",
                    ),
                    (
                        "Изображения",
                        "*.png *.ico *.jpg *.jpeg *.gif *.bmp",
                    ),
                    ("Программы", "*.exe"),
                    ("Все файлы", "*.*"),
                ],
            )
        except Exception as exc:
            logger.error("filedialog иконки упал: %r", exc)
            return

        if not path:
            return

        p = Path(path)

        if p.suffix.lower() == ".exe":
            ok, error = self._state.select_file_from_exe(p)
            if not ok:
                show_error(
                    self._dialog,
                    "Иконка не извлечена",
                    error,
                    parent_visible=self._parent_visible,
                )
                return
        else:
            self._state.select_file_as_image(str(p))

        self._auto_var.set(False)
        self._refresh_all()

    def _on_auto_toggle(self) -> None:
        if not self._auto_var.get():
            self._state.disable_auto()
            self._refresh_all()
            return

        ok, error = self._state.try_enable_auto()
        if not ok:
            self._auto_hint.configure(
                text=error,
                text_color=("#a33030", "#e88080"),
            )
            self._auto_var.set(False)
            self._refresh_all()
            return

        exe_path = self._state.exe_path
        exe_name = exe_path.name if exe_path is not None else "—"
        self._auto_hint.configure(
            text=f"Иконка взята из: {exe_name}",
            text_color=("gray40", "gray60"),
        )
        self._refresh_all()

    # --- Обновление вида ---

    def _refresh_all(self) -> None:
        self._refresh_preview()
        self._refresh_grid_highlight()
        self._refresh_auto_checkbox()

    def _refresh_preview(self) -> None:
        kind = self._state.selected_kind
        value = self._state.selected_value

        if kind == "emoji":
            self._show_emoji_preview(value)
            return

        img = load_ctk_image(value, _PREVIEW_SIZE)
        if img is not None:
            self._show_image_preview(img)
            return

        self._show_emoji_preview("❓")

    def _show_emoji_preview(self, text: str) -> None:
        self._image_preview.place_forget()
        self._image_ctk = None

        self._emoji_preview.configure(text=text)
        self._emoji_preview.place(
            relx=0.5, rely=0.5, anchor="center",
        )
        self._emoji_preview.lift()

    def _show_image_preview(self, img) -> None:
        self._emoji_preview.place_forget()

        self._image_ctk = img
        self._image_preview.configure(image=img, text="")
        self._image_preview.place(
            relx=0.5, rely=0.5, anchor="center",
        )
        self._image_preview.lift()

    def _refresh_grid_highlight(self) -> None:
        active = (
            self._state.selected_value
            if self._state.selected_kind == "emoji"
            else None
        )
        for emoji, btn in self._emoji_buttons.items():
            try:
                btn.configure(
                    fg_color=("gray70", "gray30")
                    if emoji == active else "transparent",
                )
            except Exception as exc:
                logger.debug(
                    "highlight эмодзи %r: %r", emoji, exc,
                )

    def _refresh_auto_checkbox(self) -> None:
        if not self._state.auto_available:
            return
        self._auto_var.set(self._state.is_auto)

    # --- Завершение ---

    def _on_ok(self) -> None:
        self._result = self._state.build_result()
        self._dialog.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self._dialog.destroy()


def pick_icon(
    parent,
    current_icon: str,
    current_icon_auto: bool,
    exe_path: Path | None,
    parent_visible: bool,
) -> tuple[str, bool] | None:
    """Диалог выбора иконки профиля.

    Возвращает (icon, icon_auto) или None при отмене.
    """
    state = IconPickerState(
        current_icon=current_icon,
        current_icon_auto=current_icon_auto,
        exe_path=exe_path,
    )
    return _IconPickerDialog(
        parent=parent,
        state=state,
        parent_visible=parent_visible,
    ).run()
