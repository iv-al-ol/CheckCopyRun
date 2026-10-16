"""Ленивый кэш шрифтов CustomTkinter.

CTkFont нельзя создавать до появления Tk-root, поэтому шрифты
создаются при первом обращении, а не на уровне модуля.

get_emoji_font возвращает шрифт Segoe UI Emoji — он рендерит
эмодзи в цвете на Windows (в отличие от Segoe UI).
"""

from __future__ import annotations

import customtkinter as ctk

_cache: dict[tuple[int, str], ctk.CTkFont] = {}
_emoji_cache: dict[int, ctk.CTkFont] = {}

_EMOJI_FAMILY = "Segoe UI Emoji"


def get_font(size: int, weight: str = "normal") -> ctk.CTkFont:
    """Обычный шрифт приложения (Segoe UI)."""
    key = (size, weight)
    font = _cache.get(key)
    if font is None:
        font = ctk.CTkFont(size=size, weight=weight)
        _cache[key] = font
    return font


def get_emoji_font(size: int) -> ctk.CTkFont:
    """Шрифт для эмодзи: Segoe UI Emoji (цветной рендер)."""
    font = _emoji_cache.get(size)
    if font is None:
        font = ctk.CTkFont(family=_EMOJI_FAMILY, size=size)
        _emoji_cache[size] = font
    return font
