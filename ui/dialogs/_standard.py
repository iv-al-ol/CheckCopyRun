"""Стандартные диалоги: info, warning, error, yes/no.

Тонкий слой над setup_dialog + center_on_parent + bring_to_front.
Все тексты центрированы, кнопки одинаковой ширины.
Контейнер с кнопками имеет горизонтальный отступ (padx=32),
чтобы даже при коротком тексте кнопки не прилипали к краям окна.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.components.button import (
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.dialogs._centering import (
    bring_to_front,
    center_on_parent,
    is_window_visible,
)
from ui.dialogs._setup import setup_dialog

_WRAP = 380
_BUTTON_WIDTH = 110
_BUTTON_PADX = 32


def _simple(
    parent,
    title: str,
    text: str,
    parent_visible: bool = True,
) -> None:
    dialog = setup_dialog(parent, title, parent_visible)

    ctk.CTkLabel(
        dialog,
        text=text,
        justify="center",
        anchor="center",
        wraplength=_WRAP,
    ).pack(padx=32, pady=(24, 16), fill="x")

    StyledButton(
        dialog,
        text="OK",
        variant=VARIANT_PRIMARY,
        width=_BUTTON_WIDTH,
        command=dialog.destroy,
    ).pack(pady=(0, 20), padx=_BUTTON_PADX)

    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    dialog.bind("<Return>", lambda _e: dialog.destroy())
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    center_on_parent(dialog, parent)
    bring_to_front(dialog, parent_visible)
    parent.wait_window(dialog)


def show_error(
    parent, title: str, text: str, parent_visible: bool | None = None,
) -> None:
    if parent_visible is None:
        parent_visible = is_window_visible(parent)
    _simple(parent, title, text, parent_visible)


def ask_yes_no(
    parent,
    title: str,
    text: str,
    yes_text: str = "Да",
    no_text: str = "Нет",
    parent_visible: bool | None = None,
) -> bool:
    if parent_visible is None:
        parent_visible = is_window_visible(parent)

    result = {"value": False}
    dialog = setup_dialog(parent, title, parent_visible)

    ctk.CTkLabel(
        dialog,
        text=text,
        justify="center",
        anchor="center",
        wraplength=_WRAP,
    ).pack(padx=32, pady=(24, 16), fill="x")

    btns = ctk.CTkFrame(dialog, fg_color="transparent")
    btns.pack(pady=(0, 20), padx=_BUTTON_PADX)

    def on_yes():
        result["value"] = True
        dialog.destroy()

    def on_no():
        result["value"] = False
        dialog.destroy()

    StyledButton(
        btns,
        text=yes_text,
        variant=VARIANT_PRIMARY,
        width=_BUTTON_WIDTH,
        command=on_yes,
    ).pack(side="left", padx=(0, 8))

    StyledButton(
        btns,
        text=no_text,
        variant=VARIANT_SECONDARY,
        width=_BUTTON_WIDTH,
        command=on_no,
    ).pack(side="left")

    dialog.bind("<Escape>", lambda _e: on_no())
    dialog.protocol("WM_DELETE_WINDOW", on_no)

    center_on_parent(dialog, parent)
    bring_to_front(dialog, parent_visible)
    parent.wait_window(dialog)

    return result["value"]
