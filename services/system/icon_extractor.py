"""Извлечение иконки из .exe через WinAPI.

Основной путь: PrivateExtractIconsW (user32.dll) — позволяет сразу
получить иконку нужного размера (256×256). На большинстве
современных Windows доступна.

Fallback: ExtractIconExW (shell32.dll) с извлечением всех иконок
и выбором наибольшей. Количество ограничено сверху, чтобы
случайный «мусорный» возврат не привёл к попытке выделить гигабайты.

Все операции в try/except — функция save_exe_icon никогда не
бросает наружу, возвращает None при любой проблеме. Это
гарантирует, что выбор exe в UI не будет сломан из-за ошибки
извлечения иконки.
"""

from __future__ import annotations

import ctypes
import hashlib
from ctypes import wintypes
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)

# Целевой размер иконки — 256×256 (максимум, обычно встроенный
# в современные exe).
_TARGET_ICON_SIZE = 256

# Верхняя граница на количество иконок, если ExtractIconExW
# вернёт что-то аномальное.
_MAX_ICON_COUNT = 512


# --- DLL ---

def _load_dll(name: str) -> ctypes.WinDLL | None:
    try:
        return ctypes.WinDLL(name, use_last_error=True)
    except OSError as exc:
        logger.warning("%s недоступен: %r", name, exc)
        return None


_user32 = _load_dll("user32")
_gdi32 = _load_dll("gdi32")
_shell32 = _load_dll("shell32")


# --- Типы ---

HICON = wintypes.HANDLE
HBITMAP = wintypes.HANDLE
HDC = wintypes.HANDLE
HGDIOBJ = wintypes.HANDLE


# --- Прототипы ---

def _setup_proto(
    dll: ctypes.WinDLL | None,
    name: str,
    argtypes: list[type],
    restype: type,
) -> object | None:
    if dll is None:
        return None
    func = getattr(dll, name, None)
    if func is None:
        return None
    try:
        func.argtypes = argtypes
        func.restype = restype
    except Exception as exc:
        logger.debug("Не удалось настроить прототип %s: %r", name, exc)
        return None
    return func


_extract_icon_ex = _setup_proto(
    _shell32, "ExtractIconExW",
    [
        wintypes.LPCWSTR, ctypes.c_int,
        ctypes.POINTER(HICON), ctypes.POINTER(HICON), wintypes.UINT,
    ],
    wintypes.UINT,
)

_private_extract_icons = _setup_proto(
    _user32, "PrivateExtractIconsW",
    [
        wintypes.LPCWSTR, ctypes.c_int,
        ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(HICON), ctypes.POINTER(wintypes.UINT),
        wintypes.UINT, wintypes.UINT,
    ],
    wintypes.UINT,
)

_get_icon_info = _setup_proto(
    _user32, "GetIconInfo",
    [HICON, ctypes.c_void_p],
    wintypes.BOOL,
)

_destroy_icon = _setup_proto(
    _user32, "DestroyIcon",
    [HICON],
    wintypes.BOOL,
)

_get_dc = _setup_proto(
    _user32, "GetDC",
    [wintypes.HWND],
    HDC,
)

_release_dc = _setup_proto(
    _user32, "ReleaseDC",
    [wintypes.HWND, HDC],
    ctypes.c_int,
)

_create_compatible_dc = _setup_proto(
    _gdi32, "CreateCompatibleDC",
    [HDC],
    HDC,
)

_delete_dc = _setup_proto(
    _gdi32, "DeleteDC",
    [HDC],
    wintypes.BOOL,
)

_select_object = _setup_proto(
    _gdi32, "SelectObject",
    [HDC, HGDIOBJ],
    HGDIOBJ,
)

_delete_object = _setup_proto(
    _gdi32, "DeleteObject",
    [HGDIOBJ],
    wintypes.BOOL,
)

_get_object_w = _setup_proto(
    _gdi32, "GetObjectW",
    [HGDIOBJ, ctypes.c_int, ctypes.c_void_p],
    ctypes.c_int,
)

_get_dibits = _setup_proto(
    _gdi32, "GetDIBits",
    [
        HDC, HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
    ],
    ctypes.c_int,
)


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


# --- HICON → PIL.Image ---

def _hicon_to_image(hicon: int) -> object | None:
    """HICON → PIL.Image. None при любой ошибке."""
    for func in (
        _get_icon_info, _get_dibits, _get_object_w,
        _get_dc, _release_dc, _create_compatible_dc, _delete_dc,
        _select_object, _delete_object,
    ):
        if func is None:
            return None

    try:
        from PIL import Image
    except ImportError as exc:
        logger.debug("Pillow недоступен: %r", exc)
        return None

    info = ICONINFO()
    try:
        if not _get_icon_info(hicon, ctypes.byref(info)):
            return None
    except Exception as exc:
        logger.debug("GetIconInfo: %r", exc)
        return None

    try:
        if not info.hbmColor:
            return None

        bmp = BITMAP()
        try:
            if not _get_object_w(
                info.hbmColor, ctypes.sizeof(BITMAP),
                ctypes.byref(bmp),
            ):
                return None
        except Exception as exc:
            logger.debug("GetObjectW: %r", exc)
            return None

        width = int(bmp.bmWidth)
        height = int(bmp.bmHeight)
        if width <= 0 or height <= 0:
            return None

        try:
            hdc = _get_dc(None)
        except Exception as exc:
            logger.debug("GetDC: %r", exc)
            return None
        if not hdc:
            return None

        try:
            try:
                memdc = _create_compatible_dc(hdc)
            except Exception as exc:
                logger.debug("CreateCompatibleDC: %r", exc)
                return None
            if not memdc:
                return None

            try:
                _select_object(memdc, info.hbmColor)

                bmi = BITMAPINFO()
                bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.bmiHeader.biWidth = width
                bmi.bmiHeader.biHeight = -height   # top-down
                bmi.bmiHeader.biPlanes = 1
                bmi.bmiHeader.biBitCount = 32
                bmi.bmiHeader.biCompression = 0

                buf = ctypes.create_string_buffer(width * height * 4)
                try:
                    res = _get_dibits(
                        memdc, info.hbmColor, 0, height,
                        buf, ctypes.byref(bmi), 0,
                    )
                except Exception as exc:
                    logger.debug("GetDIBits: %r", exc)
                    return None
                if res == 0:
                    return None

                img = Image.frombuffer(
                    "RGBA", (width, height),
                    buf, "raw", "BGRA", 0, 1,
                )
                return img.copy()
            finally:
                _delete_dc(memdc)
        finally:
            _release_dc(None, hdc)
    finally:
        try:
            if info.hbmColor:
                _delete_object(info.hbmColor)
            if info.hbmMask:
                _delete_object(info.hbmMask)
        except Exception as exc:
            logger.debug("DeleteObject: %r", exc)


# --- Путь 1: PrivateExtractIconsW ---

def _extract_via_private(exe_path: Path, size: int) -> object | None:
    """PrivateExtractIconsW — иконка заданного размера одним вызовом."""
    if _private_extract_icons is None:
        return None
    if _destroy_icon is None:
        return None

    try:
        phicon = (HICON * 1)()
        piconid = (wintypes.UINT * 1)()
        count = _private_extract_icons(
            str(exe_path), 0, size, size,
            phicon, piconid, 1, 0,
        )
    except Exception as exc:
        logger.debug("PrivateExtractIconsW: %r", exc)
        return None

    if not count or not phicon[0]:
        return None

    try:
        return _hicon_to_image(phicon[0])
    finally:
        try:
            _destroy_icon(phicon[0])
        except Exception as exc:
            logger.debug("DestroyIcon private: %r", exc)


# --- Путь 2: ExtractIconExW + наибольшая ---

def _hicon_size(hicon: int) -> int:
    """Ширина bitmap иконки. 0 при ошибке."""
    if _get_icon_info is None:
        return 0
    if _get_object_w is None:
        return 0
    if _delete_object is None:
        return 0

    info = ICONINFO()
    try:
        if not _get_icon_info(hicon, ctypes.byref(info)):
            return 0
    except Exception as exc:
        logger.debug("GetIconInfo size: %r", exc)
        return 0

    try:
        if not info.hbmColor:
            return 0
        bmp = BITMAP()
        try:
            if not _get_object_w(
                info.hbmColor, ctypes.sizeof(BITMAP),
                ctypes.byref(bmp),
            ):
                return 0
        except Exception as exc:
            logger.debug("GetObjectW size: %r", exc)
            return 0
        return int(bmp.bmWidth)
    finally:
        try:
            if info.hbmColor:
                _delete_object(info.hbmColor)
            if info.hbmMask:
                _delete_object(info.hbmMask)
        except Exception as exc:
            logger.debug("DeleteObject size: %r", exc)


def _extract_largest_via_enum(exe_path: Path) -> object | None:
    """ExtractIconExW: извлекаем все, выбираем наибольшую."""
    if _extract_icon_ex is None:
        return None
    if _destroy_icon is None:
        return None

    try:
        total = int(_extract_icon_ex(str(exe_path), -1, None, None, 0))
    except Exception as exc:
        logger.debug("ExtractIconExW count: %r", exc)
        return None

    if total <= 0:
        return None

    if total > _MAX_ICON_COUNT:
        logger.debug(
            "ExtractIconExW: странное количество иконок %d для %s, "
            "ограничиваю до %d",
            total, exe_path, _MAX_ICON_COUNT,
        )
        total = _MAX_ICON_COUNT

    try:
        large = (HICON * total)()
        small = (HICON * total)()
    except (MemoryError, OverflowError) as exc:
        logger.error(
            "Не удалось выделить массивы иконок (%d): %r",
            total, exc,
        )
        return None

    try:
        try:
            extracted = int(_extract_icon_ex(
                str(exe_path), 0, large, small, total,
            ))
        except Exception as exc:
            logger.debug("ExtractIconExW extract: %r", exc)
            return None

        if extracted <= 0:
            return None

        best_hicon = None
        best_size = 0

        try:
            for idx in range(extracted):
                for arr in (large, small):
                    hicon = arr[idx]
                    if not hicon:
                        continue
                    size = _hicon_size(hicon)
                    if size > best_size:
                        best_size = size
                        best_hicon = hicon

            if best_hicon is None:
                return None

            logger.debug(
                "Иконка %s: выбрана с размером %dx%d",
                exe_path, best_size, best_size,
            )
            return _hicon_to_image(best_hicon)
        finally:
            for arr in (large, small):
                for idx in range(extracted):
                    hicon = arr[idx]
                    if hicon:
                        try:
                            _destroy_icon(hicon)
                        except Exception as exc:
                            logger.debug(
                                "DestroyIcon enum: %r", exc,
                            )
    finally:
        # Страховка: если что-то пошло не так до extracted,
        # освобождаем всё, что успели получить.
        for arr in (large, small):
            for idx in range(total):
                hicon = arr[idx]
                if hicon:
                    try:
                        _destroy_icon(hicon)
                    except Exception as exc:
                        logger.debug(
                            "DestroyIcon fallback: %r", exc,
                        )


# --- Публичное API ---

def save_exe_icon(exe_path: Path, out_dir: Path) -> Path | None:
    """Извлекает иконку exe и сохраняет PNG в out_dir.

    Никогда не бросает наружу — возвращает None при любой проблеме.
    """
    try:
        if not exe_path.is_file():
            logger.debug("Файл %s не найден", exe_path)
            return None

        img = None

        # 1. Иконка целевого размера напрямую.
        img = _extract_via_private(exe_path, _TARGET_ICON_SIZE)

        # 2. Fallback: все иконки + наибольшая.
        if img is None:
            img = _extract_largest_via_enum(exe_path)

        if img is None:
            logger.debug(
                "Не удалось извлечь иконку из %s", exe_path,
            )
            return None

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Не удалось создать %s: %r", out_dir, exc)
            return None

        digest = hashlib.sha256(
            str(exe_path.resolve()).encode("utf-8"),
        ).hexdigest()[:16]
        out_path = out_dir / f"exe_{digest}.png"

        try:
            img.save(out_path, format="PNG")
        except Exception as exc:
            logger.error("Не удалось сохранить %s: %r", out_path, exc)
            return None

        logger.debug(
            "Иконка exe сохранена: %s (%dx%d)",
            out_path, img.size[0], img.size[1],
        )
        return out_path
    except Exception as exc:
        logger.error(
            "save_exe_icon упал для %s: %r", exe_path, exc,
        )
        return None
