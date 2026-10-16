"""Извлечение иконки из .exe через WinAPI (ctypes).

Берём первую (индекс 0) крупную иконку из ресурсов exe. Если крупной
нет — падаем на мелкую. Результат сохраняем как PNG, чтобы сайдбар
и диалоги могли показывать её через CTkImage.

Функция save_exe_icon кэширует результат по хэшу пути к exe: одна
и та же программа даст один и тот же PNG.

WinAPI-функции:
- ExtractIconExW  — shell32.dll
- GetIconInfo, GetDC, ReleaseDC, DestroyIcon — user32.dll
- CreateCompatibleDC, DeleteDC, SelectObject, DeleteObject,
  GetObjectW, GetDIBits — gdi32.dll
"""

from __future__ import annotations

import ctypes
import hashlib
from ctypes import wintypes
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)

# --- DLL ---

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)


# --- Типы ---

HICON = wintypes.HANDLE
HBITMAP = wintypes.HANDLE
HDC = wintypes.HANDLE
HGDIOBJ = wintypes.HANDLE


# --- Прототипы ---
# Везде, где функция может отсутствовать (теоретически на урезанных
# системах), используем getattr — при отсутствии сохраняем None,
# а save_exe_icon вернёт None без падения.

_extract_icon_ex = getattr(_shell32, "ExtractIconExW", None)
if _extract_icon_ex is not None:
    _extract_icon_ex.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int,
        ctypes.POINTER(HICON), ctypes.POINTER(HICON), wintypes.UINT,
    ]
    _extract_icon_ex.restype = wintypes.UINT

_get_icon_info = getattr(_user32, "GetIconInfo", None)
if _get_icon_info is not None:
    _get_icon_info.argtypes = [HICON, ctypes.c_void_p]
    _get_icon_info.restype = wintypes.BOOL

_destroy_icon = getattr(_user32, "DestroyIcon", None)
if _destroy_icon is not None:
    _destroy_icon.argtypes = [HICON]
    _destroy_icon.restype = wintypes.BOOL

_get_dc = getattr(_user32, "GetDC", None)
if _get_dc is not None:
    _get_dc.argtypes = [wintypes.HWND]
    _get_dc.restype = HDC

_release_dc = getattr(_user32, "ReleaseDC", None)
if _release_dc is not None:
    _release_dc.argtypes = [wintypes.HWND, HDC]
    _release_dc.restype = ctypes.c_int

_create_compatible_dc = getattr(_gdi32, "CreateCompatibleDC", None)
if _create_compatible_dc is not None:
    _create_compatible_dc.argtypes = [HDC]
    _create_compatible_dc.restype = HDC

_delete_dc = getattr(_gdi32, "DeleteDC", None)
if _delete_dc is not None:
    _delete_dc.argtypes = [HDC]
    _delete_dc.restype = wintypes.BOOL

_select_object = getattr(_gdi32, "SelectObject", None)
if _select_object is not None:
    _select_object.argtypes = [HDC, HGDIOBJ]
    _select_object.restype = HGDIOBJ

_delete_object = getattr(_gdi32, "DeleteObject", None)
if _delete_object is not None:
    _delete_object.argtypes = [HGDIOBJ]
    _delete_object.restype = wintypes.BOOL

_get_object_w = getattr(_gdi32, "GetObjectW", None)
if _get_object_w is not None:
    _get_object_w.argtypes = [HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
    _get_object_w.restype = ctypes.c_int

_get_dibits = getattr(_gdi32, "GetDIBits", None)
if _get_dibits is not None:
    _get_dibits.argtypes = [
        HDC, HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
    ]
    _get_dibits.restype = ctypes.c_int


# --- Структуры ---

class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", HBITMAP),
        ("hbmColor", HBITMAP),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


# --- Внутренние проверки ---

def _missing(func, name: str) -> bool:
    if func is None:
        logger.warning("WinAPI-функция %s недоступна", name)
        return True
    return False


# --- Конвертация ---

def _hicon_to_image(hicon):
    """HICON → PIL.Image. Импорт PIL — внутри, ленивый."""
    try:
        from PIL import Image
    except ImportError as exc:
        logger.debug("Pillow недоступен: %r", exc)
        return None

    info = ICONINFO()
    if not _get_icon_info(hicon, ctypes.byref(info)):
        logger.debug("GetIconInfo вернул 0")
        return None

    try:
        if not info.hbmColor:
            logger.debug("У иконки нет цветного битмапа")
            return None

        bmp = BITMAP()
        if not _get_object_w(
            info.hbmColor, ctypes.sizeof(BITMAP), ctypes.byref(bmp),
        ):
            logger.debug("GetObjectW вернул 0")
            return None

        width = int(bmp.bmWidth)
        height = int(bmp.bmHeight)
        if width <= 0 or height <= 0:
            logger.debug("Некорректные размеры иконки: %dx%d", width, height)
            return None

        hdc = _get_dc(None)
        if not hdc:
            logger.debug("GetDC вернул 0")
            return None

        memdc = _create_compatible_dc(hdc)
        if not memdc:
            _release_dc(None, hdc)
            logger.debug("CreateCompatibleDC вернул 0")
            return None

        try:
            _select_object(memdc, info.hbmColor)

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height   # top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0    # BI_RGB

            buf = ctypes.create_string_buffer(width * height * 4)
            res = _get_dibits(
                memdc, info.hbmColor, 0, height,
                buf, ctypes.byref(bmi), 0,
            )
            if res == 0:
                logger.debug("GetDIBits вернул 0")
                return None

            img = Image.frombuffer(
                "RGBA", (width, height), buf, "raw", "BGRA", 0, 1,
            )
            return img.copy()
        finally:
            _delete_dc(memdc)
            _release_dc(None, hdc)
    finally:
        if info.hbmColor:
            _delete_object(info.hbmColor)
        if info.hbmMask:
            _delete_object(info.hbmMask)


def _extract_first_icon(exe_path: Path):
    """Возвращает PIL.Image первой иконки exe, либо None."""
    try:
        large = (HICON * 1)()
        small = (HICON * 1)()
        count = _extract_icon_ex(
            str(exe_path), 0, large, small, 1,
        )
    except Exception as exc:
        logger.error("ExtractIconExW упал для %s: %r", exe_path, exc)
        return None

    if count == 0:
        logger.debug("У %s нет иконок", exe_path)
        return None

    hicon = large[0] or small[0]
    if not hicon:
        logger.debug("ExtractIconExW не вернул HICON для %s", exe_path)
        return None

    try:
        return _hicon_to_image(hicon)
    finally:
        if large[0]:
            _destroy_icon(large[0])
        if small[0] and small[0] != large[0]:
            _destroy_icon(small[0])


# --- Публичное API ---

def save_exe_icon(exe_path: Path, out_dir: Path) -> Path | None:
    """Извлекает первую иконку exe и сохраняет PNG в out_dir.

    Возвращает путь к PNG или None при неудаче.
    """
    if _missing(_extract_icon_ex, "ExtractIconExW"):
        return None
    if _missing(_get_icon_info, "GetIconInfo"):
        return None
    if _missing(_get_dibits, "GetDIBits"):
        return None

    if not exe_path.is_file():
        logger.debug("Файл %s не найден", exe_path)
        return None

    img = _extract_first_icon(exe_path)
    if img is None:
        return None

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Не удалось создать %s: %r", out_dir, exc)
        return None

    digest = hashlib.sha1(
        str(exe_path.resolve()).encode("utf-8"),
    ).hexdigest()[:16]
    out_path = out_dir / f"exe_{digest}.png"

    try:
        img.save(out_path, format="PNG")
    except Exception as exc:
        logger.error("Не удалось сохранить %s: %r", out_path, exc)
        return None

    logger.debug("Иконка exe сохранена: %s", out_path)
    return out_path
