"""Центрирование диалогов относительно родителя или монитора.

Ключевые функции:
  • center_on_parent(dialog, parent) — центрирует по центру окна
    (если родитель видим) или по центру монитора, на котором окно
    было в последний раз (если свёрнуто/скрыто в трей).
  • bring_to_front(dialog, parent_visible) — поднимает, фокусирует.

Для свёрнутого/скрытого родителя используется WinAPI
MonitorFromRect — чтобы правильно определить монитор из нескольких.
Если метод get_last_visible_rect недоступен у parent — fallback на
центр виртуального экрана.
"""

from __future__ import annotations

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import win32api
    import win32con
except ImportError:
    win32api = None
    win32con = None

_FOCUS_DELAY_MS = 50
_MINIMIZED_COORD_MARKER = -30000


# --- Виртуальный экран и мониторы ---

def get_virtual_screen(
    dialog: ctk.CTkToplevel,
) -> tuple[int, int, int, int]:
    """(x, y, w, h) виртуального экрана (все мониторы)."""
    if win32api is not None and win32con is not None:
        try:
            x = int(win32api.GetSystemMetrics(
                win32con.SM_XVIRTUALSCREEN,
            ))
            y = int(win32api.GetSystemMetrics(
                win32con.SM_YVIRTUALSCREEN,
            ))
            w = int(win32api.GetSystemMetrics(
                win32con.SM_CXVIRTUALSCREEN,
            ))
            h = int(win32api.GetSystemMetrics(
                win32con.SM_CYVIRTUALSCREEN,
            ))
            if w > 0 and h > 0:
                return x, y, w, h
        except Exception as exc:
            logger.debug(
                "GetSystemMetrics(VIRTUALSCREEN) не удался: %r", exc,
            )

    return (
        0, 0,
        dialog.winfo_screenwidth(),
        dialog.winfo_screenheight(),
    )


def get_monitor_for_rect(
    left: int, top: int, right: int, bottom: int,
) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) монитора, ближайшего к прямоугольнику."""
    if win32api is None or win32con is None:
        return None

    try:
        hmon = win32api.MonitorFromRect(
            (left, top, right, bottom),
            win32con.MONITOR_DEFAULTTONEAREST,
        )
        info = win32api.GetMonitorInfo(hmon)
        rc = info["Monitor"]
    except Exception as exc:
        logger.debug(
            "MonitorFromRect / GetMonitorInfo не удался: %r", exc,
        )
        return None

    try:
        mx, my, mr, mb = int(rc[0]), int(rc[1]), int(rc[2]), int(rc[3])
    except (TypeError, ValueError, IndexError) as exc:
        logger.debug("некорректный MonitorInfo: %r", exc)
        return None

    mw = mr - mx
    mh = mb - my
    if mw <= 0 or mh <= 0:
        return None
    return mx, my, mw, mh


# --- DPI и состояние окна ---

def get_scaling(window) -> float:
    try:
        value = ctk.ScalingTracker.get_window_dpi_scaling(window)
        if value and value > 0:
            return float(value)
    except Exception as exc:
        logger.debug("ScalingTracker недоступен: %r", exc)
    return 1.0


def is_window_visible(window) -> bool:
    try:
        state = window.winfo_toplevel().state()
    except Exception as exc:
        logger.debug("не удалось прочитать state окна: %r", exc)
        return False
    return state in ("normal", "zoomed")


def window_rect(window) -> tuple[int, int, int, int] | None:
    """Прямоугольник окна (left, top, right, bottom) в Tk-координатах.

    None для свёрнутого окна — Windows ставит маркер (-32000).
    """
    try:
        top = window.winfo_toplevel()
        x = int(top.winfo_rootx())
        y = int(top.winfo_rooty())
        w = int(top.winfo_width())
        h = int(top.winfo_height())
    except Exception as exc:
        logger.debug(
            "не удалось получить прямоугольник окна: %r", exc,
        )
        return None

    if w <= 1 or h <= 1:
        return None

    if x <= _MINIMIZED_COORD_MARKER or y <= _MINIMIZED_COORD_MARKER:
        return None

    return x, y, x + w, y + h


# --- Целевая точка для центрирования ---

def target_center(
    dialog: ctk.CTkToplevel, parent,
) -> tuple[int, int]:
    scaling = get_scaling(dialog)

    try:
        top = parent.winfo_toplevel()
        state = top.state()
    except Exception as exc:
        logger.debug("не удалось прочитать state окна: %r", exc)
        state = "normal"
        top = parent

    if state in ("withdrawn", "iconic"):
        return _target_center_for_hidden(dialog, top, scaling)
    return _target_center_for_visible(dialog, top, scaling)


def _target_center_for_visible(
    dialog: ctk.CTkToplevel, top, scaling: float,
) -> tuple[int, int]:
    try:
        pw = top.winfo_width()
        ph = top.winfo_height()
        px = top.winfo_rootx()
        py = top.winfo_rooty()
    except Exception as exc:
        logger.debug("не удалось получить геометрию окна: %r", exc)
        pw = ph = 0

    if pw <= 1 or ph <= 1:
        return _target_center_for_hidden(dialog, top, scaling)
    return px + pw // 2, py + ph // 2


def _target_center_for_hidden(
    dialog: ctk.CTkToplevel, top, scaling: float,
) -> tuple[int, int]:
    """Центр монитора (или виртуального экрана) в ФИЗИЧЕСКИХ пикселях.

    Единицы важны: результат подставляется в wm_geometry вместе с
    winfo_* размерами, а они физические. Возврат логических значений
    смещал диалог к левому верхнему углу при DPI > 100%.
    """
    rect = window_rect(top)

    if rect is None:
        getter = getattr(top, "get_last_visible_rect", None)
        if callable(getter):
            try:
                rect = getter()
            except Exception as exc:
                logger.debug("get_last_visible_rect упал: %r", exc)
                rect = None

    if rect is not None:
        win_left = int(rect[0] * scaling)
        win_top = int(rect[1] * scaling)
        win_right = int(rect[2] * scaling)
        win_bottom = int(rect[3] * scaling)

        monitor = get_monitor_for_rect(
            win_left, win_top, win_right, win_bottom,
        )
        if monitor is not None:
            mx, my, mw, mh = monitor
            return mx + mw // 2, my + mh // 2

    vx, vy, vw, vh = get_virtual_screen(dialog)
    return vx + vw // 2, vy + vh // 2


# --- Публичные операции ---

def center_on_parent(dialog: ctk.CTkToplevel, parent) -> None:
    """Центрирует диалог относительно родителя или монитора.

    Использует wm_geometry (не CTk-переопределённый geometry),
    чтобы избежать двойного применения DPI-scaling.
    """
    dialog.update_idletasks()

    dw = dialog.winfo_reqwidth()
    dh = dialog.winfo_reqheight()

    if dw <= 1 or dh <= 1:
        logger.debug(
            "center_on_parent: размер диалога ещё не готов (%dx%d)",
            dw, dh,
        )
        return

    target_cx, target_cy = target_center(dialog, parent)

    x = target_cx - dw // 2
    y = target_cy - dh // 2

    try:
        dialog.wm_geometry(f"{dw}x{dh}+{x}+{y}")
    except Exception as exc:
        logger.debug("wm_geometry диалога: %r", exc)
        return

    logger.debug(
        "center_on_parent: диалог %dx%d+%d+%d (target=%d,%d)",
        dw, dh, x, y, target_cx, target_cy,
    )


def bring_to_front(
    dialog: ctk.CTkToplevel, parent_visible: bool,
) -> None:
    if not parent_visible:
        try:
            dialog.attributes("-topmost", True)
        except Exception as exc:
            logger.debug("-topmost не удался: %r", exc)

    try:
        dialog.lift()
    except Exception as exc:
        logger.debug("lift не удался: %r", exc)

    dialog.after(_FOCUS_DELAY_MS, dialog.focus_force)
