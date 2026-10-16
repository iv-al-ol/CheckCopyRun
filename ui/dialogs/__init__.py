"""Универсальные диалоги, стилизованные под CustomTkinter."""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from ui.components.button import (
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import win32api
    import win32con
except ImportError:
    win32api = None
    win32con = None

_WRAP = 380
_FOCUS_DELAY_MS = 50
_MINIMIZED_COORD_MARKER = -30000

# Кэш PhotoImage для иконки диалогов — держим один объект,
# чтобы не пересоздавать на каждый диалог и не терять на GC.
_icon_photo_cache = None
_icon_photo_loaded = False


# --- Иконка диалога ---

def _get_icon_path() -> Path | None:
    # ui/dialogs/__init__.py → корень проекта = три уровня вверх.
    root = Path(__file__).resolve().parent.parent.parent
    icon = root / "assets" / "icon.ico"
    if not icon.exists():
        logger.debug("Иконка диалога не найдена: %s", icon)
        return None
    return icon


def apply_dialog_icon(dialog: ctk.CTkToplevel) -> None:
    """Ставит иконку приложения на диалог. Оба способа, оба с логом."""
    global _icon_photo_cache, _icon_photo_loaded

    icon_path = _get_icon_path()
    if icon_path is None:
        return

    try:
        dialog.iconbitmap(str(icon_path))
    except Exception as exc:
        logger.debug("iconbitmap диалога: %r", exc)

    if _icon_photo_loaded:
        if _icon_photo_cache is not None:
            try:
                dialog.iconphoto(False, _icon_photo_cache)
            except Exception as exc:
                logger.debug("iconphoto диалога: %r", exc)
        return

    _icon_photo_loaded = True

    try:
        from PIL import Image, ImageTk
    except ImportError as exc:
        logger.debug("Pillow недоступен для иконки диалога: %r", exc)
        return

    try:
        img = Image.open(icon_path)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        _icon_photo_cache = ImageTk.PhotoImage(img)
    except Exception as exc:
        logger.warning("Не удалось построить PhotoImage иконки: %r", exc)
        return

    try:
        dialog.iconphoto(False, _icon_photo_cache)
    except Exception as exc:
        logger.debug("iconphoto диалога (первый раз): %r", exc)


# --- Фабрика диалогов ---

def setup_dialog(
    parent,
    title: str,
    parent_visible: bool = True,
) -> ctk.CTkToplevel:
    """Создаёт CTkToplevel с заголовком, иконкой и grab_set.

    Используется всеми диалогами проекта — стандартными здесь и
    специализированными в ui/dialogs/profile_dialogs.py и
    ui/components/icon_picker.py.
    """
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    apply_dialog_icon(dialog)

    if parent_visible:
        try:
            dialog.transient(parent.winfo_toplevel())
        except Exception as exc:
            logger.debug("transient() не удался: %r", exc)

    try:
        dialog.grab_set()
    except Exception as exc:
        logger.debug("grab_set не удался: %r", exc)

    return dialog


# --- Центрирование и фокус ---

def _get_virtual_screen(
    dialog: ctk.CTkToplevel,
) -> tuple[int, int, int, int]:
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


def _get_monitor_for_rect(
    left: int, top: int, right: int, bottom: int,
) -> tuple[int, int, int, int] | None:
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


def _get_scaling(window) -> float:
    try:
        value = ctk.ScalingTracker.get_window_dpi_scaling(window)
        if value and value > 0:
            return float(value)
    except Exception as exc:
        logger.debug("ScalingTracker недоступен: %r", exc)
    return 1.0


def _is_window_visible(window) -> bool:
    try:
        state = window.winfo_toplevel().state()
    except Exception as exc:
        logger.debug("не удалось прочитать state окна: %r", exc)
        return False
    return state in ("normal", "zoomed")


def _window_rect(window) -> tuple[int, int, int, int] | None:
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


def _target_center(
    dialog: ctk.CTkToplevel, parent,
) -> tuple[int, int]:
    scaling = _get_scaling(dialog)

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
    rect = _window_rect(top)

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

        monitor = _get_monitor_for_rect(
            win_left, win_top, win_right, win_bottom,
        )
        if monitor is not None:
            mx, my, mw, mh = monitor
            mx_tk = int(mx / scaling)
            my_tk = int(my / scaling)
            mw_tk = int(mw / scaling)
            mh_tk = int(mh / scaling)
            return mx_tk + mw_tk // 2, my_tk + mh_tk // 2

    vx, vy, vw, vh = _get_virtual_screen(dialog)
    vx_tk = int(vx / scaling)
    vy_tk = int(vy / scaling)
    vw_tk = int(vw / scaling)
    vh_tk = int(vh / scaling)
    return vx_tk + vw_tk // 2, vy_tk + vh_tk // 2


def center_on_parent(dialog: ctk.CTkToplevel, parent) -> None:
    dialog.update_idletasks()

    dw = dialog.winfo_reqwidth()
    dh = dialog.winfo_reqheight()

    target_cx, target_cy = _target_center(dialog, parent)

    dialog.geometry(f"{dw}x{dh}+0+0")
    dialog.update_idletasks()

    frame_left = dialog.winfo_rootx()
    frame_top = dialog.winfo_rooty()

    outer_w = dw + 2 * frame_left
    outer_h = dh + frame_top + frame_left

    new_x = target_cx - outer_w // 2
    new_y = target_cy - outer_h // 2

    dialog.geometry(f"+{new_x}+{new_y}")


def bring_to_front(dialog: ctk.CTkToplevel, parent_visible: bool) -> None:
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


# --- Стандартные диалоги ---

def _simple(
    parent,
    title: str,
    text: str,
    parent_visible: bool = True,
) -> None:
    dialog = setup_dialog(parent, title, parent_visible)

    ctk.CTkLabel(
        dialog,
        text=text,
        justify="center",
        anchor="center",
        wraplength=_WRAP,
    ).pack(padx=28, pady=(24, 16), fill="x")

    StyledButton(
        dialog,
        text="OK",
        variant=VARIANT_PRIMARY,
        width=110,
        command=dialog.destroy,
    ).pack(pady=(0, 20))

    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    dialog.bind("<Return>", lambda _e: dialog.destroy())
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    center_on_parent(dialog, parent)
    bring_to_front(dialog, parent_visible)
    parent.wait_window(dialog)


def show_info(
    parent, title: str, text: str, parent_visible: bool | None = None,
) -> None:
    if parent_visible is None:
        parent_visible = _is_window_visible(parent)
    _simple(parent, title, text, parent_visible)


def show_warning(
    parent, title: str, text: str, parent_visible: bool | None = None,
) -> None:
    if parent_visible is None:
        parent_visible = _is_window_visible(parent)
    _simple(parent, title, text, parent_visible)


def show_error(
    parent, title: str, text: str, parent_visible: bool | None = None,
) -> None:
    if parent_visible is None:
        parent_visible = _is_window_visible(parent)
    _simple(parent, title, text, parent_visible)


def ask_yes_no(
    parent,
    title: str,
    text: str,
    yes_text: str = "Да",
    no_text: str = "Нет",
    parent_visible: bool | None = None,
) -> bool:
    if parent_visible is None:
        parent_visible = _is_window_visible(parent)

    result = {"value": False}
    dialog = setup_dialog(parent, title, parent_visible)

    ctk.CTkLabel(
        dialog,
        text=text,
        justify="center",
        anchor="center",
        wraplength=_WRAP,
    ).pack(padx=32, pady=(24, 16), fill="x")

    btns = ctk.CTkFrame(dialog, fg_color="transparent")
    btns.pack(pady=(0, 20))

    def on_yes():
        result["value"] = True
        dialog.destroy()

    def on_no():
        result["value"] = False
        dialog.destroy()

    StyledButton(
        btns,
        text=yes_text,
        variant=VARIANT_PRIMARY,
        width=110,
        command=on_yes,
    ).pack(side="left", padx=(0, 8))

    StyledButton(
        btns,
        text=no_text,
        variant=VARIANT_SECONDARY,
        width=110,
        command=on_no,
    ).pack(side="left")

    dialog.bind("<Escape>", lambda _e: on_no())
    dialog.protocol("WM_DELETE_WINDOW", on_no)

    center_on_parent(dialog, parent)
    bring_to_front(dialog, parent_visible)
    parent.wait_window(dialog)

    return result["value"]
