"""Единая загрузка картинок в CTkImage.

Логический размер идёт в CTkImage(size=...), а исходник
загружается с запасом ×max_scaling_hint — чтобы при DPI > 100%
не было мыла. CTk сам масштабирует картинку под текущий DPI.

При ошибке (Pillow нет, файл битый, путь неверный) возвращает
None — вызывающий fallback'ает на эмодзи или заглушку.
"""

from __future__ import annotations

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_SCALING_HINT = 4

_IMAGE_EXTS = (".png", ".ico", ".jpg", ".jpeg", ".gif", ".bmp")


def looks_like_image_path(value: str) -> bool:
    """Похоже ли значение на путь к файлу-картинке."""
    if not value:
        return False
    if "/" in value or "\\" in value:
        return True
    return value.lower().endswith(_IMAGE_EXTS)


def load_ctk_image(
    path: str,
    logical_size: int,
    *,
    max_scaling_hint: int = _DEFAULT_SCALING_HINT,
) -> ctk.CTkImage | None:
    """Загружает картинку и возвращает CTkImage или None.

    logical_size — размер в логических пикселях, которые CTk
    отмасштабирует под DPI. Исходник хранится увеличенным в
    max_scaling_hint раз, чтобы при 200–400% DPI не было мыла.
    """
    if not path or logical_size <= 0:
        return None

    try:
        from PIL import Image
    except ImportError as exc:
        logger.debug("Pillow недоступен: %r", exc)
        return None

    try:
        img = Image.open(path).convert("RGBA")
        max_side = logical_size * max(1, max_scaling_hint)
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        return ctk.CTkImage(
            light_image=img,
            dark_image=img,
            size=(logical_size, logical_size),
        )
    except Exception as exc:
        logger.debug("Картинка %s не загружена: %r", path, exc)
        return None
