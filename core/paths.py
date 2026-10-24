"""Работа с системными путями и валидация путей.

Documents через WinAPI (корректно работает с OneDrive и
перенесёнными папками). Ресурсы через __file__ с учётом
Nuitka-сборки. Проверки: конфликт source/destination.

Длинные пути Windows (>260): хелперы to_long_path /
from_long_path / display_path. Порог — LONG_PATH_THRESHOLD
символов. Специальный длинный префикс применяется только для
файловых операций; для отображения и внешних инструментов
(explorer, subprocess) используется исходный путь.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)

# FOLDERID_Documents = {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
_FOLDERID_Documents = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"


# --- Documents через WinAPI ---

class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


def _parse_guid(s: str) -> _GUID:
    s = s.strip("{}")
    parts = s.split("-")
    d4 = bytes.fromhex(parts[4])
    return _GUID(
        int(parts[0], 16),
        int(parts[1], 16),
        int(parts[2], 16),
        (ctypes.c_byte * 8)(*d4),
    )


def _documents_via_winapi() -> Path | None:
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    except OSError as exc:
        logger.debug("shell32/ole32 недоступны: %r", exc)
        return None

    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT

    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None

    guid = _parse_guid(_FOLDERID_Documents)
    ptr = ctypes.c_wchar_p()

    try:
        hr = shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(ptr),
        )
    except OSError as exc:
        logger.debug("SHGetKnownFolderPath бросил: %r", exc)
        return None

    if hr != 0 or not ptr.value:
        logger.debug("SHGetKnownFolderPath hr=%s", hr)
        return None

    try:
        return Path(ptr.value)
    finally:
        ole32.CoTaskMemFree(ptr)


def get_documents_dir() -> Path:
    """Documents пользователя. Fallback — %USERPROFILE%/Documents."""
    via_api = _documents_via_winapi()
    if via_api is not None:
        return via_api

    fallback = (
        Path(os.environ.get("USERPROFILE", str(Path.home())))
        / "Documents"
    )
    logger.debug("Documents через fallback: %s", fallback)
    return fallback


# --- Ресурсы ---

def get_resource_root() -> Path:
    """Корень ресурсов приложения."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_asset_path(name: str) -> Path:
    """Путь к файлу из assets/."""
    return get_resource_root() / "assets" / name


# --- Длинные пути Windows ---

MAX_PATH = 260
# Порог для применения длинного префикса — оставляем запас на
# имя файла и расширение (обычно до 12 символов).
LONG_PATH_THRESHOLD = 248

# Префикс длинных путей: две обратные косые черты, вопросительный
# знак, обратная косая черта (результирующая строка).
_LONG_PREFIX = "\\\\?\\"
# UNC-вариант: тот же префикс + "UNC" + обратная косая черта.
_UNC_PREFIX = "\\\\?\\UNC\\"


def is_long_path(path: str | os.PathLike) -> bool:
    """True, если путь близок к MAX_PATH или превысил его."""
    if not path:
        return False
    try:
        abs_p = os.path.abspath(str(path))
    except OSError:
        return False
    return len(abs_p) >= LONG_PATH_THRESHOLD


def to_long_path(path: str | os.PathLike) -> str:
    """Приводит путь к виду, пригодному для I/O с длинными путями.

    Всегда возвращает абсолютный путь (os.path.abspath).
    Если длина >= LONG_PATH_THRESHOLD — добавляет специальный
    длинный префикс (или UNC-вариант для сетевых путей).
    Иначе возвращает абсолютный путь без префикса.

    Уже префиксованный путь возвращается как есть.
    """
    p = str(path)
    if not p:
        return p
    if p.startswith(_LONG_PREFIX):
        return p
    try:
        abs_p = os.path.abspath(p)
    except OSError:
        return p
    if len(abs_p) < LONG_PATH_THRESHOLD:
        return abs_p

    abs_p = abs_p.replace("/", "\\")
    if abs_p.startswith("\\\\"):
        return _UNC_PREFIX + abs_p[2:]
    return _LONG_PREFIX + abs_p


def from_long_path(path: str | os.PathLike) -> str:
    """Убирает специальный длинный префикс, если он есть."""
    p = str(path)
    if p.startswith(_UNC_PREFIX):
        return "\\\\" + p[len(_UNC_PREFIX):]
    if p.startswith(_LONG_PREFIX):
        return p[len(_LONG_PREFIX):]
    return p


def display_path(path: str | os.PathLike) -> str:
    """Путь для отображения в UI (без специального префикса)."""
    return from_long_path(str(path))


# --- Проверки и подготовка директорий ---

def ensure_directory(path: str) -> bool:
    """Гарантирует, что директория существует.

    Если её нет — создаёт (включая промежуточные). True при
    успехе, False если путь пуст или создать не удалось.
    """
    if not path:
        return False
    try:
        target = to_long_path(path)
    except OSError as exc:
        logger.debug("ensure_directory: %r", exc)
        return False
    if os.path.isdir(target):
        return True
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        logger.debug("ensure_directory: makedirs %s: %r", path, exc)
        return False
    logger.info("Пересоздана директория: %s", path)
    return True


# Расширения, которые считаются файлами-картинками в UI.
IMAGE_EXTENSIONS = (".png", ".ico", ".jpg", ".jpeg", ".gif", ".bmp")


def looks_like_image_path(value: str) -> bool:
    """Похоже ли значение на путь к файлу-картинке."""
    if not value:
        return False
    if "/" in value or "\\" in value:
        return True
    return value.lower().endswith(IMAGE_EXTENSIONS)


def _compare_key(path: str) -> str:
    """Ключ для сравнения путей. Не ходит в ФС, работает с
    длинными путями (без Path.resolve)."""
    try:
        abs_p = os.path.abspath(path)
    except OSError:
        return path
    return os.path.normcase(abs_p)


def _is_strictly_inside(child: str, parent: str) -> bool:
    """True, если child строго внутри parent (не равен)."""
    c = child.rstrip("\\/") + os.sep
    p = parent.rstrip("\\/") + os.sep
    return c != p and c.startswith(p)


def path_conflict_error(
    source: str, destination: str,
) -> str | None:
    """Текст конфликта source/destination или None.

    Конфликт — совпадение путей или вложенность в любую сторону.
    Сравнение через os.path.abspath + normcase, без Path.resolve
    (resolve не поддерживает длинные пути на Windows).
    """
    if not source or not destination:
        return None

    try:
        src = _compare_key(source)
        dst = _compare_key(destination)
    except OSError as exc:
        logger.debug(
            "сравнение путей %r / %r: %r", source, destination, exc,
        )
        return None

    if src == dst:
        return "Исходная и целевая директории совпадают"

    if _is_strictly_inside(dst, src):
        return "Целевая директория находится внутри исходной"
    if _is_strictly_inside(src, dst):
        return "Исходная директория находится внутри целевой"

    return None
