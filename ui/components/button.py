"""Кнопки в едином стиле приложения."""

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ui.fonts import get_font
from ui.palette import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_TEXT,
    DANGER,
    DANGER_HOVER,
    DANGER_TEXT,
    SURFACE_BG,
    SURFACE_HOVER,
    SURFACE_RADIUS,
    SURFACE_TEXT,
)

_DEFAULT_FONT_SIZE = 13
_DEFAULT_HEIGHT = 32

VARIANT_PRIMARY = "primary"
VARIANT_SECONDARY = "secondary"
VARIANT_DANGER = "danger"

_VARIANT_STYLES: dict[str, dict[str, Any]] = {
    VARIANT_PRIMARY: {
        "fg_color": ACCENT,
        "hover_color": ACCENT_HOVER,
        "text_color": ACCENT_TEXT,
    },
    VARIANT_SECONDARY: {
        "fg_color": SURFACE_BG,
        "hover_color": SURFACE_HOVER,
        "text_color": SURFACE_TEXT,
    },
    VARIANT_DANGER: {
        "fg_color": DANGER,
        "hover_color": DANGER_HOVER,
        "text_color": DANGER_TEXT,
    },
}


class StyledButton(ctk.CTkButton):
    """
    Кнопка в одном из стандартных стилей приложения.

    variant:
      - "primary"   — акцентное действие (синяя);
      - "secondary" — второстепенное действие (серая);
      - "danger"    — опасное действие (красная).

    Любые нестандартные свойства можно передать через **kwargs —
    они переопределят дефолтные значения варианта.
    """

    def __init__(
        self,
        master,
        *,
        text: str = "",
        variant: str = VARIANT_PRIMARY,
        command: Callable[[], None] | None = None,
        width: int = 140,
        height: int = _DEFAULT_HEIGHT,
        **kwargs: Any,
    ):
        style = _VARIANT_STYLES.get(
            variant, _VARIANT_STYLES[VARIANT_PRIMARY]
        )

        merged: dict[str, Any] = {
            "fg_color": style["fg_color"],
            "hover_color": style["hover_color"],
            "text_color": style["text_color"],
            "corner_radius": SURFACE_RADIUS,
            "font": get_font(_DEFAULT_FONT_SIZE),
        }
        merged.update(kwargs)

        super().__init__(
            master,
            text=text,
            command=command,
            width=width,
            height=height,
            **merged,
        )
