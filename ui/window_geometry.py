"""Геометрия главного окна: сохранение, восстановление, DPI.

Все функции, кроме WindowGeometryTracker, — чистые либо почти
чистые (читают только системные метрики). Тестируются без tkinter
через моки.

WindowGeometryTracker — маленький помощник, который по <Configure>
запоминает последний видимый прямоугольник окна. Диалоги потом
читают его через get_last_visible_rect(), чтобы открыться на
правильном мониторе, если окно свёрнуто или скрыто в трей.

Сохраняем и восстанавливаем в ЛОГИЧЕСКИХ пикселях: CTk при
установке geometry() умножает значения на DPI-scale. winfo_*
возвращают физические. Если сохранять физические и восстанавливать
как логические — окно будет расти при каждом запуске на HiDPI.
"""

from __future__ import annotations

import ctypes
import re

import customtkinter as ctk

from config.constants import (
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_DEFAULT_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")

_MIN_VISIBLE_PX = 100
_MINIMIZED_COORD_MARKER = -30000

_INITIAL_RECT_DELAY_MS = 80

# WinAPI GetSystemMetrics: индексы для виртуального экрана.
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

# WinAPI SystemParametersInfo: рабочая область монитора (без панели задач).
_SPI_GETWORKAREA = 0x0030


# --- Разбор строки ---

def parse_geometry(
    geometry: str,
) -> tuple[int, int, int, int] | None:
    """Разбирает 'WxH+X+Y' в (w, h, x, y) или None."""
    match = _GEOMETRY_RE.match(geometry)
    if not match:
        return None
    try:
        return (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
        )
    except (TypeError, ValueError) as exc:
        logger.debug("parse_geometry: %r", exc)
        return None


def is_valid_geometry_string(geometry: str) -> bool:
    return _GEOMETRY_RE.match(geometry) is not None


# --- DPI и виртуальный экран ---

def get_dpi_scaling(window) -> float:
    """Коэффициент DPI-масштабирования CTk для окна (1.0 = 100%)."""
    try:
        value = ctk.ScalingTracker.get_window_dpi_scaling(window)
        if value and value > 0:
            return float(value)
    except Exception as exc:
        logger.debug("ScalingTracker недоступен: %r", exc)
    return 1.0


def get_virtual_screen_physical(
) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) виртуального экрана (все мониторы вместе).

    Физические пиксели. None при ошибке — вызывающий использует
    fallback.
    """
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except OSError as exc:
        logger.debug("user32 недоступен: %r", exc)
        return None

    try:
        x = int(user32.GetSystemMetrics(_SM_XVIRTUALSCREEN))
        y = int(user32.GetSystemMetrics(_SM_YVIRTUALSCREEN))
        w = int(user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN))
        h = int(user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN))
    except Exception as exc:
        logger.debug("GetSystemMetrics(VIRTUALSCREEN): %r", exc)
        return None

    if w <= 0 or h <= 0:
        return None
    return x, y, w, h


def is_inside_virtual_screen(
    x: int, y: int, w: int, h: int, scaling: float,
) -> bool:
    """Проверяет, что окно (в логических пикселях) видно на экране."""
    vs = get_virtual_screen_physical()
    if vs is None:
        # Не проверить — пропускаем (лучше рискнуть, чем сбросить).
        return True

    vs_x, vs_y, vs_w, vs_h = vs
    vs_x = int(vs_x / scaling)
    vs_y = int(vs_y / scaling)
    vs_w = int(vs_w / scaling)
    vs_h = int(vs_h / scaling)

    overlap_w = min(x + w, vs_x + vs_w) - max(x, vs_x)
    overlap_h = min(y + h, vs_y + vs_h) - max(y, vs_y)

    return (
        overlap_w >= _MIN_VISIBLE_PX
        and overlap_h >= _MIN_VISIBLE_PX
    )


# --- Рабочая область и минимальный размер ---

def get_work_area_logical(window) -> tuple[int, int] | None:
    """(ширина, высота) рабочей области основного монитора.

    Логические пиксели (без панели задач). None при ошибке.
    """
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except OSError as exc:
        logger.debug("user32 недоступен: %r", exc)
        return None

    class _Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = _Rect()
    try:
        ok = user32.SystemParametersInfoW(
            _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0,
        )
        if not ok:
            return None
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
    except Exception as exc:
        logger.debug("SPI_GETWORKAREA: %r", exc)
        return None

    if width <= 0 or height <= 0:
        return None

    scaling = get_dpi_scaling(window) or 1.0
    return int(width / scaling), int(height / scaling)


def effective_min_size(window) -> tuple[int, int]:
    """Минимальный размер окна, вписанный в рабочую область.

    На небольших экранах с высоким DPI (1366x768 при 150-200%)
    номинальный минимум больше доступной высоты — окно стало бы
    неуменьшаемым, а низ UI недоступным.
    """
    w = WINDOW_MIN_WIDTH
    h = WINDOW_MIN_HEIGHT

    work = get_work_area_logical(window)
    if work is None:
        return w, h

    work_w, work_h = work
    return min(w, work_w), min(h, work_h)


# --- Операции с окном ---

def apply_default_geometry(window) -> None:
    """Стартовый размер — `WINDOW_DEFAULT_*`, по центру рабочей области.

    Дефолтный размер больше минимального: форма профиля со
    всеми примечаниями помещается без полосы прокрутки. На
    маленьком экране или высоком DPI клампится по рабочей
    области — пользователь увидит скроллбар, но интерфейс
    останется рабочим.

    Значения в логических пикселях: CTk умножит их на
    DPI-scaling при установке.
    """
    min_w, min_h = effective_min_size(window)

    scaling = get_dpi_scaling(window) or 1.0
    work = get_work_area_logical(window)
    if work is not None:
        sw, sh = work
    else:
        try:
            sw = int(window.winfo_screenwidth() / scaling)
            sh = int(window.winfo_screenheight() / scaling)
        except Exception as exc:
            logger.debug("размер экрана недоступен: %r", exc)
            sw = WINDOW_DEFAULT_WIDTH
            sh = WINDOW_DEFAULT_HEIGHT

    # Клампим дефолт по рабочей области и по минимальному
    # размеру: окно не должно вылезать за экран и не должно
    # быть меньше minsize.
    w = max(min_w, min(WINDOW_DEFAULT_WIDTH, sw))
    h = max(min_h, min(WINDOW_DEFAULT_HEIGHT, sh))

    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    window.geometry(f"{w}x{h}+{x}+{y}")


def try_restore_geometry(window, geometry: str) -> bool:
    """Применяет сохранённую геометрию, если она валидна и на экране."""
    parsed = parse_geometry(geometry)
    if parsed is None:
        return False

    w, h, x, y = parsed

    if w < WINDOW_MIN_WIDTH or h < WINDOW_MIN_HEIGHT:
        logger.debug(
            "Сохранённый размер %dx%d меньше минимального", w, h,
        )
        return False

    scaling = get_dpi_scaling(window) or 1.0
    if not is_inside_virtual_screen(x, y, w, h, scaling):
        logger.debug(
            "Окно %dx%d+%d+%d вне видимой области", w, h, x, y,
        )
        return False

    try:
        window.geometry(geometry)
        logger.debug("Восстановлена геометрия: %r", geometry)
        return True
    except Exception as exc:
        logger.debug("geometry(%r) не сработал: %r", geometry, exc)
        return False


def capture_geometry(window) -> str | None:
    """Текущая геометрия окна (в логических пикселях) или None.

    winfo_* возвращает физические. Делим на DPI-scale, чтобы при
    следующем запуске CTk умножил их обратно и окно имело тот же
    визуальный размер.
    """
    try:
        w = window.winfo_width()
        h = window.winfo_height()
        x = window.winfo_x()
        y = window.winfo_y()
    except Exception as exc:
        logger.debug("Не удалось прочитать геометрию окна: %r", exc)
        return None

    if w <= 1 or h <= 1:
        return None

    scaling = get_dpi_scaling(window) or 1.0
    lw = int(round(w / scaling))
    lh = int(round(h / scaling))
    lx = int(round(x / scaling))
    ly = int(round(y / scaling))
    return f"{lw}x{lh}+{lx}+{ly}"


# --- Трекер последней видимой позиции ---

class WindowGeometryTracker:
    """Запоминает последний видимый прямоугольник окна.

    Нужен диалогам: если окно свёрнуто или скрыто в трей, они
    открываются по центру монитора, где окно было в последний раз.
    """

    def __init__(self, window):
        self._window = window
        self._last_rect: tuple[int, int, int, int] | None = None

    def start(self) -> None:
        self._window.bind(
            "<Configure>", self._on_configure, add="+",
        )
        self._window.after(
            _INITIAL_RECT_DELAY_MS, self._on_configure,
        )

    def get_last_visible_rect(
        self,
    ) -> tuple[int, int, int, int] | None:
        return self._last_rect

    def _on_configure(self, event=None) -> None:
        if event is not None and (
            getattr(event, "widget", None) is not self._window
        ):
            return

        try:
            state = self._window.state()
        except Exception as exc:
            logger.debug("state(): %r", exc)
            return

        if state != "normal":
            return

        try:
            x = int(self._window.winfo_rootx())
            y = int(self._window.winfo_rooty())
            w = int(self._window.winfo_width())
            h = int(self._window.winfo_height())
        except Exception as exc:
            logger.debug("геометрия last_visible_rect: %r", exc)
            return

        if w <= 1 or h <= 1:
            return

        if (
            x <= _MINIMIZED_COORD_MARKER
            or y <= _MINIMIZED_COORD_MARKER
        ):
            return

        self._last_rect = (x, y, x + w, y + h)
