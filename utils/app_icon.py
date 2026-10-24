"""Иконка приложения icon.ico из папки assets/.

Предупреждение PIL "Image was not the expected size" для
нестандартных .ico — игнорируется локально.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)


def get_app_icon_path() -> Path | None:
    """Путь к assets/icon.ico или None, если файла нет."""
    root = Path(__file__).resolve().parent.parent
    path = root / "assets" / "icon.ico"
    if not path.exists():
        logger.debug("icon.ico не найден: %s", path)
        return None
    return path


def apply_window_icon(window) -> None:
    """Ставит иконку приложения на окно (главное или диалог)."""
    icon_path = get_app_icon_path()
    if icon_path is None:
        return

    try:
        window.iconbitmap(str(icon_path))
    except Exception as exc:
        logger.debug("iconbitmap для %r: %r", window, exc)

    try:
        from PIL import Image, ImageTk

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Image was not the expected size",
                category=UserWarning,
            )
            img = Image.open(icon_path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            photo = ImageTk.PhotoImage(img)
        window.iconphoto(False, photo)
        window._icon_photo_ref = photo
    except ImportError as exc:
        logger.debug("Pillow недоступен для iconphoto: %r", exc)
    except Exception as exc:
        logger.debug("iconphoto для %r: %r", window, exc)
