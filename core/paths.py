"""Работа с системными путями и валидация путей.

Documents через WinAPI (корректно работает с OneDrive и
перенесёнными папками). Ресурсы через __file__ с учётом
Nuitka-сборки. Проверки: конфликт source/destination.
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
    """Корень ресурсов приложения.

    Работает в трёх режимах:
      • исходники — от __file__ модуля;
      • Nuitka --standalone — тот же __file__, но внутри .dist;
      • Nuitka --onefile — __file__ ведёт в распакованную
        временную папку, где тоже есть assets/.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent.parent


def get_asset_path(name: str) -> Path:
    """Путь к файлу из assets/."""
    return get_resource_root() / "assets" / name


# --- Проверки ---

def is_valid_directory(path: str) -> bool:
    return bool(path) and os.path.isdir(path)


def is_valid_file(path: str) -> bool:
    return bool(path) and os.path.isfile(path)


def path_conflict_error(
    source: str, destination: str,
) -> str | None:
    """Текст конфликта source/destination или None.

    Конфликт — совпадение путей или вложенность в любую сторону.
    Все три случая ведут к рекурсивной перезаписи или копированию
    в себя.
    """
    if not source or not destination:
        return None

    try:
        src = Path(source).resolve()
        dst = Path(destination).resolve()
    except OSError as exc:
        logger.debug(
            "resolve путей %r / %r: %r", source, destination, exc,
        )
        return None

    if src == dst:
        return "Исходная и целевая директории совпадают"

    try:
        if src in dst.parents:
            return "Целевая директория находится внутри исходной"
        if dst in src.parents:
            return "Исходная директория находится внутри целевой"
    except Exception as exc:
        logger.debug("проверка вложенности путей: %r", exc)

    return None
