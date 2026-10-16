"""Всплывающая подсказка при наведении курсора.

Дизайн повторяет context_menu и option_menu: плашка SURFACE_BG
с тонкой рамкой SURFACE_BORDER и скруглёнными углами.

Публичное API:
    show()             — показать принудительно
    hide()             — скрыть принудительно
    destroy()          — отвязать от виджета и освободить ресурсы
    set_text(text)     — обновить текст
    is_visible         — True, если подсказка сейчас видна

Текст — строка или callable. Callable удобен для полей, значение
которых меняется (например, «Полный путь: ...»).

Одновременно видна только одна подсказка. Глобальный трекер
гарантирует это вне зависимости от порядка <Enter>/<Leave>.
"""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from ui.fonts import get_font
from ui.palette import (
    SURFACE_BG,
    SURFACE_BORDER,
    SURFACE_RADIUS,
    SURFACE_TEXT,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# --- Настройки по умолчанию ---
_DEFAULT_DELAY_MS = 500
_DEFAULT_WRAPLENGTH = 320
_FONT_SIZE = 12

# --- Геометрия (логические пиксели) ---
_FRAME_PAD = 8
_CURSOR_OFFSET = 12
_SCREEN_MARGIN = 8

_LEAVE_CHECK_DELAY_MS = 20

TooltipText = str | Callable[[], str]


# --- Глобальный трекер активной подсказки ---

_active_tooltip: Tooltip | None = None


def _register_active(tooltip: Tooltip) -> None:
    """Регистрирует tooltip как активный, вытесняя предыдущий."""
    global _active_tooltip
    previous = _active_tooltip
    _active_tooltip = tooltip

    if previous is None or previous is tooltip:
        return

    try:
        previous.hide()
    except Exception as exc:
        logger.debug("hide предыдущего tooltip: %r", exc)


def _unregister_active(tooltip: Tooltip) -> None:
    """Снимает tooltip с учёта, если он всё ещё активный."""
    global _active_tooltip
    if _active_tooltip is tooltip:
        _active_tooltip = None


def _get_scaling(widget) -> float:
    """Коэффициент DPI-масштабирования CTk для виджета."""
    try:
        value = ctk.ScalingTracker.get_widget_scaling(widget)
        if value and value > 0:
            return float(value)
    except Exception as exc:
        logger.debug("ScalingTracker.get_widget_scaling: %r", exc)
    return 1.0


class Tooltip:
    """Подсказка, привязанная к конкретному виджету."""

    def __init__(
        self,
        widget,
        text: TooltipText,
        *,
        delay_ms: int = _DEFAULT_DELAY_MS,
        wraplength: int = _DEFAULT_WRAPLENGTH,
    ):
        self._widget = widget
        self._text = text
        self._delay_ms = delay_ms
        self._wraplength = wraplength

        self._top: ctk.CTkToplevel | None = None
        self._show_job: str | None = None
        self._leave_job: str | None = None

        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_press, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    # --- Публичное API ---

    @property
    def is_visible(self) -> bool:
        return self._top is not None

    def show(self) -> None:
        self._cancel_show_job()
        self._do_show()

    def hide(self) -> None:
        _unregister_active(self)
        self._close_window()

    def destroy(self) -> None:
        self._cancel_jobs()
        self.hide()
        self._widget = None

    def set_text(self, text: TooltipText) -> None:
        self._text = text

    # --- Обработчики виджета ---

    def _on_enter(self, _event=None) -> None:
        if self._widget is None:
            return
        self._cancel_jobs()
        try:
            self._show_job = self._widget.after(
                self._delay_ms, self._do_show,
            )
        except Exception as exc:
            logger.debug("after() для tooltip: %r", exc)

    def _on_leave(self, _event=None) -> None:
        if self._widget is None:
            return
        self._cancel_show_job()
        try:
            self._leave_job = self._widget.after(
                _LEAVE_CHECK_DELAY_MS, self._check_leave,
            )
        except Exception as exc:
            logger.debug("after() при Leave tooltip: %r", exc)

    def _on_press(self, _event=None) -> None:
        self._cancel_jobs()
        self.hide()

    def _on_destroy(self, event=None) -> None:
        if event is not None and event.widget is not self._widget:
            return
        self.destroy()

    # --- Проверка «реально ли ушли» ---

    def _check_leave(self) -> None:
        self._leave_job = None
        if self._widget is None:
            return

        try:
            under = self._widget.winfo_containing(
                self._widget.winfo_pointerx(),
                self._widget.winfo_pointery(),
            )
        except Exception as exc:
            logger.debug("winfo_containing tooltip: %r", exc)
            under = None

        if under is not None and self._is_inside(under):
            return

        self.hide()

    def _is_inside(self, widget) -> bool:
        current = widget
        while current is not None:
            if current is self._widget:
                return True
            current = getattr(current, "master", None)
        return False

    # --- Показ ---

    def _do_show(self) -> None:
        self._show_job = None
        if self._widget is None:
            return

        if self._top is not None:
            _register_active(self)
            return

        text = self._resolve_text().strip()
        if not text:
            return

        try:
            top = ctk.CTkToplevel(self._widget)
        except Exception as exc:
            logger.error("Не удалось создать окно tooltip: %r", exc)
            return

        top.overrideredirect(True)
        try:
            top.attributes("-topmost", True)
        except Exception as exc:
            logger.debug("attributes(-topmost) у tooltip: %r", exc)

        outer = ctk.CTkFrame(
            top,
            fg_color=SURFACE_BG,
            corner_radius=SURFACE_RADIUS,
            border_width=1,
            border_color=SURFACE_BORDER,
        )
        outer.pack(fill="both", expand=True)

        ctk.CTkLabel(
            outer,
            text=text,
            anchor="w",
            justify="left",
            wraplength=self._wraplength,
            text_color=SURFACE_TEXT,
            font=get_font(_FONT_SIZE),
        ).pack(padx=_FRAME_PAD, pady=_FRAME_PAD)

        top.update_idletasks()

        self._top = top
        self._position(top)

        _register_active(self)

    def _resolve_text(self) -> str:
        if callable(self._text):
            try:
                return str(self._text())
            except Exception as exc:
                logger.debug("callable текста tooltip упал: %r", exc)
                return ""
        return self._text or ""

    def _position(self, top: ctk.CTkToplevel) -> None:
        try:
            wx = self._widget.winfo_rootx()
            wy = self._widget.winfo_rooty()
            wh = self._widget.winfo_height()
        except Exception as exc:
            logger.debug("геометрия виджета для tooltip: %r", exc)
            return

        tw = top.winfo_reqwidth()
        th = top.winfo_reqheight()

        # Смещения в физических пикселях с учётом DPI.
        scaling = _get_scaling(self._widget)
        cursor_offset = round(_CURSOR_OFFSET * scaling)
        screen_margin = round(_SCREEN_MARGIN * scaling)

        x = wx
        y = wy + wh + cursor_offset

        try:
            sw = top.winfo_screenwidth()
            sh = top.winfo_screenheight()
        except Exception as exc:
            logger.debug("размер экрана для tooltip: %r", exc)
            sw = sh = 0

        if sw and x + tw > sw - screen_margin:
            x = max(screen_margin, sw - tw - screen_margin)

        if sh and y + th > sh - screen_margin:
            y = max(screen_margin, wy - th - cursor_offset)

        top.geometry(f"+{x}+{y}")

    def _close_window(self) -> None:
        if self._top is None:
            return
        top = self._top
        self._top = None
        try:
            top.destroy()
        except Exception as exc:
            logger.debug("destroy tooltip: %r", exc)

    # --- Управление заданиями after ---

    def _cancel_show_job(self) -> None:
        if self._show_job is None or self._widget is None:
            return
        try:
            self._widget.after_cancel(self._show_job)
        except Exception as exc:
            logger.debug("after_cancel show tooltip: %r", exc)
        self._show_job = None

    def _cancel_leave_job(self) -> None:
        if self._leave_job is None or self._widget is None:
            return
        try:
            self._widget.after_cancel(self._leave_job)
        except Exception as exc:
            logger.debug("after_cancel leave tooltip: %r", exc)
        self._leave_job = None

    def _cancel_jobs(self) -> None:
        self._cancel_show_job()
        self._cancel_leave_job()
