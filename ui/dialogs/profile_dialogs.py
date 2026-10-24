"""Диалоги работы с профилями: переименование, удаление.

ask_delete_profiles:
  • один профиль  — диалог 420 px, заголовок с именем;
  • несколько     — диалог 440 px, заголовок «Удалить профили?»
                    без числа (список ниже уже показывает кого),
                    превью списка до _DELETE_PREVIEW_LIMIT имён,
                    по центру.

Кнопки «Удалить» / «Отмена» отцентрированы с гарантированным
отступом от краёв: btns_padx считается так, чтобы диалог был
шириной не меньше dialog_width независимо от длины текста.
"""

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

# Ширина диалога. Multi чуть шире single — там список профилей,
# но без излишней ширины: 440 px достаточно с запасом.
_DIALOG_WIDTH = 420
_DIALOG_WIDTH_MULTI = 440

_RENAME_BUTTON_WIDTH = 140
_DELETE_BUTTON_WIDTH = 130
_DELETE_BUTTON_GAP = 8

# Сколько профилей показать в списке подтверждения удаления.
_DELETE_PREVIEW_LIMIT = 8


# --- Переименование ---

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


# --- Удаление ---

def _delete_buttons_padx(dialog_width: int) -> int:
    """Отступ контейнера кнопок от краёв диалога.

    Гарантирует минимальную ширину диалога:
    buttons_width + 2*padx = dialog_width.
    Даёт кнопкам визуальный отступ от границ даже если
    окружающий текст короче.
    """
    buttons_width = (
        2 * _DELETE_BUTTON_WIDTH + _DELETE_BUTTON_GAP
    )
    padx = (dialog_width - buttons_width) // 2
    return max(32, padx)


def ask_delete_profiles(
    parent,
    names: list[str],
    parent_visible: bool,
) -> bool:
    """Подтверждение удаления одного или нескольких профилей.

    names — display_name профилей. Для одного — простой диалог
    с именем, для нескольких — заголовок без числа + превью
    списка (имена уже показаны, дублировать число незачем).
    """
    if not names:
        return False

    result = {"value": False}

    is_multi = len(names) > 1
    dialog_width = (
        _DIALOG_WIDTH_MULTI if is_multi else _DIALOG_WIDTH
    )
    content_width = dialog_width - 48
    btns_padx = _delete_buttons_padx(dialog_width)

    dialog = setup_dialog(parent, "Удаление профиля", parent_visible)

    if len(names) == 1:
        title = f"Удалить профиль «{names[0]}»?"
    else:
        title = "Удалить профили?"
    subtitle = "Это действие нельзя отменить."

    ctk.CTkLabel(
        dialog,
        text=title,
        anchor="center",
        justify="center",
        wraplength=content_width,
        font=get_font(14, "bold"),
    ).pack(padx=32, pady=(24, 4), fill="x")

    if is_multi:
        preview_lines = [
            f"• {n}"
            for n in names[:_DELETE_PREVIEW_LIMIT]
        ]
        extra = len(names) - _DELETE_PREVIEW_LIMIT
        if extra > 0:
            preview_lines.append(f"… и ещё {extra}")

        ctk.CTkLabel(
            dialog,
            text="\n".join(preview_lines),
            anchor="center",
            justify="center",
            wraplength=content_width,
            font=get_font(11),
        ).pack(padx=32, pady=(0, 8), fill="x")

    ctk.CTkLabel(
        dialog,
        text=subtitle,
        anchor="center",
        justify="center",
        wraplength=content_width,
        text_color=("gray40", "gray60"),
        font=get_font(11),
    ).pack(padx=32, pady=(0, 16), fill="x")

    btns = ctk.CTkFrame(dialog, fg_color="transparent")
    btns.pack(pady=(0, 20), padx=btns_padx)

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
    ).pack(
        side="left", padx=(0, _DELETE_BUTTON_GAP),
    )

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
