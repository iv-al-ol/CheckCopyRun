"""Диалог выбора иконки профиля.

Возможности:
- выбор эмодзи из палитры (без поля ввода);
- выбор файла изображения (PNG, ICO, JPG, GIF, BMP);
- ручное извлечение иконки из произвольного exe (в диалоге выбора
  файла достаточно выбрать .exe — берём первую иконку);
- автоматическое извлечение иконки из exe самого профиля — по
  чекбоксу «Иконка приложения». Чекбокс активен, только если путь
  exe задан в профиле.

Приоритет пользователя выше авто: клик по эмодзи, по файлу или
по exe (вручную) снимает чекбокс и сохраняет icon_auto=False.

Превью эмодзи и превью файла/иконки exe — два независимых
виджета. В каждый момент виден только один.

Возвращает (icon, icon_auto) или None при отмене.
"""

from __future__ import annotations

import hashlib
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from config.constants import DEFAULT_PROFILE_ICON
from core.settings_store import get_icons_dir
from services.icon_extractor import save_exe_icon
from ui.components.button import (
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
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

# Запас на HiDPI при загрузке исходника превью.
_MAX_SCALING_HINT = 4

_ACTION_BUTTON_WIDTH = 150

_GRID_COLS = 8

_EMOJI_PALETTE: list[str] = [
    "📁", "📂", "🗂", "📦", "🚀", "⚙", "🔧", "💾",
    "🖥", "🌐", "⭐", "🧩", "🎯", "🎨", "🔨", "🛠",
    "📊", "📈", "📉", "💼", "💻", "🖱", "⌨", "🖨",
    "🗄", "🔒", "🔑", "🧭", "🧪", "⚗", "🔍", "📌",
]


def _separator_hex() -> str:
    if ctk.get_appearance_mode() == "Dark":
        return "#4a4a4a"
    return "#b8b8b8"


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    if "/" in value or "\\" in value:
        return True
    return value.lower().endswith(_IMAGE_EXTS)


def _load_ctk_image(path: str, logical_size: int):
    """CTkImage: исходник с запасом на HiDPI, size — логический.

    CTkImage сам умножает size на текущий scaling. Поэтому мы
    передаём логический размер (например, 64), а исходник храним
    увеличенным в _MAX_SCALING_HINT раз — чтобы при 200–400% DPI
    не было мыла.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        logger.debug("Pillow недоступен для превью: %r", exc)
        return None

    try:
        img = Image.open(path).convert("RGBA")
        max_side = logical_size * _MAX_SCALING_HINT
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        return ctk.CTkImage(
            light_image=img, dark_image=img,
            size=(logical_size, logical_size),
        )
    except Exception as exc:
        logger.debug("Превью %s не построено: %r", path, exc)
        return None


class _IconPickerDialog:
    """Внутреннее состояние диалога и логика выбора."""

    def __init__(
        self,
        parent,
        current_icon: str,
        current_icon_auto: bool,
        exe_path: Path | None,
        parent_visible: bool,
    ):
        self._parent = parent
        self._parent_visible = parent_visible
        self._exe_path = exe_path

        self._result: tuple[str, bool] | None = None

        if current_icon_auto and exe_path is not None:
            existing = self._lookup_cached_exe_png(exe_path)
            if existing is not None:
                self._selected_kind = "auto"
                self._selected_value = str(existing)
            else:
                self._selected_kind = "emoji"
                self._selected_value = (
                    current_icon if not _looks_like_path(current_icon)
                    else DEFAULT_PROFILE_ICON
                )
        elif _looks_like_path(current_icon):
            self._selected_kind = "file"
            self._selected_value = current_icon
        elif current_icon:
            self._selected_kind = "emoji"
            self._selected_value = current_icon
        else:
            self._selected_kind = "emoji"
            self._selected_value = DEFAULT_PROFILE_ICON

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

        if self._exe_path is None:
            self._auto_checkbox.configure(state="disabled")
            self._auto_hint.configure(
                text=(
                    "Сначала выберите запускаемое приложение в "
                    "настройках профиля."
                ),
            )
        else:
            self._auto_hint.configure(
                text=f"Источник: {self._exe_path.name}",
            )

    def _add_separator(self, row: int) -> int:
        sep = tk.Frame(
            self._dialog,
            height=1,
            bg=_separator_hex(),
            bd=0,
            highlightthickness=0,
        )
        sep.grid(
            row=row, column=0, sticky="ew",
            padx=24, pady=(4, 12),
        )
        sep.grid_propagate(False)
        return row + 1

    # --- Выбор ---

    def _select_emoji(self, emoji: str) -> None:
        self._selected_kind = "emoji"
        self._selected_value = emoji
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
            png = save_exe_icon(p, get_icons_dir())
            if png is None:
                show_error(
                    self._dialog,
                    "Иконка не извлечена",
                    (
                        f"Не удалось извлечь иконку из файла:\n"
                        f"{p.name}"
                    ),
                    parent_visible=self._parent_visible,
                )
                return
            self._selected_kind = "file"
            self._selected_value = str(png)
        else:
            self._selected_kind = "file"
            self._selected_value = str(p.resolve())

        self._auto_var.set(False)
        self._refresh_all()

    def _on_auto_toggle(self) -> None:
        if not self._auto_var.get():
            if self._selected_kind == "auto":
                self._selected_kind = "emoji"
                self._selected_value = DEFAULT_PROFILE_ICON
            self._refresh_all()
            return

        if self._exe_path is None:
            self._auto_var.set(False)
            return

        png = save_exe_icon(self._exe_path, get_icons_dir())
        if png is None:
            self._auto_hint.configure(
                text="Не удалось извлечь иконку из exe.",
                text_color=("#a33030", "#e88080"),
            )
            self._auto_var.set(False)
            self._refresh_all()
            return

        self._selected_kind = "auto"
        self._selected_value = str(png)
        self._auto_hint.configure(
            text=f"Иконка взята из: {self._exe_path.name}",
            text_color=("gray40", "gray60"),
        )
        self._refresh_all()

    def _lookup_cached_exe_png(self, exe_path: Path) -> Path | None:
        digest = hashlib.sha1(
            str(exe_path.resolve()).encode("utf-8"),
        ).hexdigest()[:16]
        candidate = get_icons_dir() / f"exe_{digest}.png"
        if candidate.is_file():
            return candidate
        return None

    # --- Обновление вида ---

    def _refresh_all(self) -> None:
        self._refresh_preview()
        self._refresh_grid_highlight()
        self._refresh_auto_checkbox()

    def _refresh_preview(self) -> None:
        if self._selected_kind == "emoji":
            self._show_emoji_preview(self._selected_value)
            return

        img = _load_ctk_image(self._selected_value, _PREVIEW_SIZE)
        if img is not None:
            self._show_image_preview(img)
            return

        self._show_emoji_preview("❓")

    def _show_emoji_preview(self, text: str) -> None:
        self._image_preview.place_forget()
        self._image_ctk = None

        self._emoji_preview.configure(text=text)
        self._emoji_preview.place(relx=0.5, rely=0.5, anchor="center")
        self._emoji_preview.lift()

    def _show_image_preview(self, img) -> None:
        self._emoji_preview.place_forget()

        self._image_ctk = img
        self._image_preview.configure(image=img, text="")
        self._image_preview.place(relx=0.5, rely=0.5, anchor="center")
        self._image_preview.lift()

    def _refresh_grid_highlight(self) -> None:
        active = (
            self._selected_value
            if self._selected_kind == "emoji"
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
        if self._exe_path is None:
            return
        self._auto_var.set(self._selected_kind == "auto")

    # --- Завершение ---

    def _on_ok(self) -> None:
        if self._selected_kind == "auto":
            self._result = (self._selected_value, True)
        else:
            self._result = (
                self._selected_value or DEFAULT_PROFILE_ICON,
                False,
            )
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

    exe_path — путь к exe профиля. Если None — чекбокс «Иконка
    приложения» недоступен.

    Возвращает (icon, icon_auto) или None при отмене.
    """
    return _IconPickerDialog(
        parent=parent,
        current_icon=current_icon,
        current_icon_auto=current_icon_auto,
        exe_path=exe_path,
        parent_visible=parent_visible,
    ).run()
