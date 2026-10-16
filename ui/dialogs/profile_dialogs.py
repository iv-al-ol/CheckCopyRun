"""Диалоги работы с профилями: переименование, удаление."""

from __future__ import annotations

import customtkinter as ctk

from ui.components.button import (
    VARIANT_DANGER,
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.components.clipboard import enable_clipboard
from ui.dialogs import (
    bring_to_front,
    center_on_parent,
    setup_dialog,
)
from ui.fonts import get_font
from utils.logger import get_logger

logger = get_logger(__name__)

_DIALOG_WIDTH = 420

# Ширина кнопок в ряду — одинаковая для всех кнопок ряда.
_RENAME_BUTTON_WIDTH = 140
_DELETE_BUTTON_WIDTH = 130


def ask_profile_name(
    parent,
    current: str,
    parent_visible: bool,
) -> str | None:
    """Возвращает новое имя или None при отмене/пустом вводе."""
    result: dict[str, str | None] = {"value": None}

    dialog = setup_dialog(parent, "Переименовать профиль", parent_visible)

    ctk.CTkLabel(
        dialog,
        text="Новое имя профиля:",
        anchor="center",
        justify="center",
        font=get_font(13, "bold"),
    ).pack(fill="x", padx=24, pady=(20, 6))

    entry = ctk.CTkEntry(dialog, width=_DIALOG_WIDTH - 48)
    entry.pack(padx=24, pady=(0, 8))
    entry.insert(0, current)
    entry.select_range(0, "end")
    enable_clipboard(entry)

    ctk.CTkLabel(
        dialog,
        text=(
            "После ручного переименования автоматическое имя "
            "больше не применяется."
        ),
        anchor="center",
        justify="center",
        wraplength=_DIALOG_WIDTH - 48,
        text_color=("gray40", "gray60"),
        font=get_font(11),
    ).pack(fill="x", padx=24, pady=(0, 16))

    btns = ctk.CTkFrame(dialog, fg_color="transparent")
    btns.pack(pady=(0, 20))

    def on_ok() -> None:
        text = entry.get().strip()
        if not text:
            return
        result["value"] = text
        dialog.destroy()

    def on_cancel() -> None:
        result["value"] = None
        dialog.destroy()

    StyledButton(
        btns, text="Сохранить",
        variant=VARIANT_PRIMARY,
        width=_RENAME_BUTTON_WIDTH,
        command=on_ok,
    ).pack(side="left", padx=(0, 8))

    StyledButton(
        btns, text="Отмена",
        variant=VARIANT_SECONDARY,
        width=_RENAME_BUTTON_WIDTH,
        command=on_cancel,
    ).pack(side="left")

    dialog.bind("<Return>", lambda _e: on_ok())
    dialog.bind("<Escape>", lambda _e: on_cancel())
    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    entry.focus_set()

    center_on_parent(dialog, parent)
    bring_to_front(dialog, parent_visible)
    parent.wait_window(dialog)

    return result["value"]


def ask_delete_profile(
    parent,
    name: str,
    parent_visible: bool,
) -> bool:
    """Подтверждение удаления профиля. True — удалить."""
    result = {"value": False}

    dialog = setup_dialog(parent, "Удаление профиля", parent_visible)

    ctk.CTkLabel(
        dialog,
        text=f"Удалить профиль «{name}»?",
        anchor="center",
        justify="center",
        wraplength=_DIALOG_WIDTH - 48,
        font=get_font(14, "bold"),
    ).pack(padx=32, pady=(24, 4), fill="x")

    ctk.CTkLabel(
        dialog,
        text="Это действие нельзя отменить.",
        anchor="center",
        justify="center",
        text_color=("gray40", "gray60"),
        font=get_font(11),
    ).pack(padx=32, pady=(0, 16), fill="x")

    btns = ctk.CTkFrame(dialog, fg_color="transparent")
    btns.pack(pady=(0, 20))

    def on_delete() -> None:
        result["value"] = True
        dialog.destroy()

    def on_cancel() -> None:
        result["value"] = False
        dialog.destroy()

    StyledButton(
        btns, text="Удалить",
        variant=VARIANT_DANGER,
        width=_DELETE_BUTTON_WIDTH,
        command=on_delete,
    ).pack(side="left", padx=(0, 8))

    StyledButton(
        btns, text="Отмена",
        variant=VARIANT_SECONDARY,
        width=_DELETE_BUTTON_WIDTH,
        command=on_cancel,
    ).pack(side="left")

    dialog.bind("<Escape>", lambda _e: on_cancel())
    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    center_on_parent(dialog, parent)
    bring_to_front(dialog, parent_visible)
    parent.wait_window(dialog)

    return result["value"]
