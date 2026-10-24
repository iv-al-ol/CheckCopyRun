"""Иконка окна приложения (главного окна и диалогов).

Единая точка установки иконки: кэширует PhotoImage, чтобы не
пересоздавать его для каждого окна. Иконка ставится двумя
способами: iconbitmap (для заголовка окна) и iconphoto через PIL
(для панели задач и случаев, когда iconbitmap не сработал).

Предупреждение PIL "Image was not the expected size" для
нестандартных .ico — игнорируется локально: это не ошибка,
просто запись в .ico не совпадает с реальным bitmap.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import customtkinter as ctk

from core.paths import get_asset_path
from utils.logger import get_logger

logger = get_logger(__name__)

_icon_photo_cache = None
_icon_photo_loaded = False


def get_icon_path() -> Path | None:
    """Путь к assets/icon.ico или None."""
    icon = get_asset_path("icon.ico")
    if not icon.exists():
        logger.debug("Иконка окна не найдена: %s", icon)
        return None
    return icon


def apply_app_icon(window, *, taskbar: bool = False) -> None:
    """Устанавливает иконку приложения на окно.

    taskbar=True — иконка ставится как иконка приложения
    (главное окно); taskbar=False — как иконка конкретного
    окна (диалоги).
    """
    global _icon_photo_cache, _icon_photo_loaded

    icon_path = get_icon_path()
    if icon_path is None:
        return

    try:
        window.iconbitmap(str(icon_path))
    except Exception as exc:
        logger.debug("iconbitmap окна: %r", exc)

    if _icon_photo_loaded:
        if _icon_photo_cache is not None:
            try:
                window.iconphoto(taskbar, _icon_photo_cache)
            except Exception as exc:
                logger.debug("iconphoto окна: %r", exc)
        return

    _icon_photo_loaded = True

    try:
        from PIL import Image, ImageTk
    except ImportError as exc:
        logger.debug("Pillow недоступен для иконки окна: %r", exc)
        return

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Image was not the expected size",
                category=UserWarning,
            )
            img = Image.open(icon_path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            _icon_photo_cache = ImageTk.PhotoImage(img)
    except Exception as exc:
        logger.warning("Не удалось построить PhotoImage иконки: %r", exc)
        return

    try:
        window.iconphoto(taskbar, _icon_photo_cache)
    except Exception as exc:
        logger.debug("iconphoto окна (первый раз): %r", exc)


def apply_dialog_icon(dialog: ctk.CTkToplevel) -> None:
    """Устанавливает иконку приложения на диалог."""
    apply_app_icon(dialog)
