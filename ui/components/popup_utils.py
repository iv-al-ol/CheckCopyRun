"""Общие утилиты для всплывающих окон (меню, подсказки).

Раньше `_get_scaling`, `_make_transparent` и `is_inside`
дублировались в `context_menu.py`, `tooltip.py`, `nav_item.py`
и `profile_tile.py`.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger(__name__)

# Служебный цвет для прозрачных углов.
TRANSPARENT_COLOR = "#ff00fe"


def get_scaling(widget) -> float:
    """Масштаб виджета под текущий DPI (1.0 при ошибке)."""
    try:
        value = ctk.ScalingTracker.get_widget_scaling(widget)
        if value and value > 0:
            return float(value)
    except Exception as exc:
        logger.debug("ScalingTracker.get_widget_scaling: %r", exc)
    return 1.0


def make_transparent(window: tk.Toplevel) -> None:
    """Убирает фон Toplevel через chroma-key."""
    try:
        window.configure(bg=TRANSPARENT_COLOR)
    except Exception as exc:
        logger.debug("configure(bg) у Toplevel: %r", exc)
        return

    try:
        window.attributes("-transparentcolor", TRANSPARENT_COLOR)
    except Exception as exc:
        logger.debug("-transparentcolor: %r", exc)


def is_inside(widget, ancestor) -> bool:
    """True, если widget — сам ancestor или его потомок."""
    current = widget
    while current is not None:
        if current is ancestor:
            return True
        current = getattr(current, "master", None)
    return False
