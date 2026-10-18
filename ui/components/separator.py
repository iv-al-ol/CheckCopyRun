"""Горизонтальный разделитель в стиле приложения.

Использует tk.Frame — не проходит через CTk-масштабирование,
поэтому ровно 1 физический пиксель при любом DPI.

Цвет — под текущую тему: тёмная #4a4a4a, светлая #b8b8b8.
Единая точка правки для всех разделителей проекта.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from config.constants import SEPARATOR_HEIGHT

_SEPARATOR_DARK = "#4a4a4a"
_SEPARATOR_LIGHT = "#b8b8b8"


def separator_color() -> str:
    """Hex-цвет разделителя под текущую тему."""
    if ctk.get_appearance_mode() == "Dark":
        return _SEPARATOR_DARK
    return _SEPARATOR_LIGHT


def make_separator(
    parent,
    *,
    color: str | None = None,
    height: int = SEPARATOR_HEIGHT,
) -> tk.Frame:
    """Создаёт горизонтальный разделитель и возвращает его.

    Родитель решает, куда его упаковать и с какими padx/pady.
    grid_propagate(False) уже выставлен — высота ровно `height`.
    """
    sep = tk.Frame(
        parent,
        height=height,
        bg=color if color is not None else separator_color(),
        bd=0,
        highlightthickness=0,
    )
    sep.grid_propagate(False)
    sep.pack_propagate(False)
    return sep
