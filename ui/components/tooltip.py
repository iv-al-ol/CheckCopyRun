"""Всплывающая подсказка при наведении курсора.

Дизайн повторяет context_menu и option_menu: плашка SURFACE_BG
с тонкой рамкой SURFACE_BORDER и скруглёнными углами.

Скругления: окно прямоугольное, углы вне скруглённой рамки
заполняются служебным цветом и становятся прозрачными через
-transparentcolor (Windows).

Показ: окно создаётся скрытым (withdraw), настраивается,
позиционируется, затем deiconify.

Скрытие:
  • fast-path: <Leave> → проверка через 80 мс (мгновенно);
  • safety: polling каждые 200 мс, пока тултип видим. Проверяет
    позицию указателя через winfo_containing. Надёжнее таймаута:
    скрывает, даже если <Leave> не пришёл (быстрая смена фокуса,
    перетаскивание окна, quirks Tk). Polling не мешает показу,
    пока указатель действительно на виджете или на самом
    тултипе;
  • глобальный трекер: показ нового тултипа скрывает предыдущий;
  • <ButtonPress> на виджете;
  • <Destroy> виджета.

Публичное API:
    show()             — показать принудительно
    hide()             — скрыть принудительно
    destroy()          — отвязать от виджета и освободить ресурсы
    set_text(text)     — обновить текст
    is_visible         — True, если подсказка сейчас видна

Текст — строка или callable.

Одновременно видна только одна подсказка.
"""

from __future__ import annotations

import tkinter as tk
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

# Задержка проверки «курсор всё ещё внутри» после <Leave>:
# если <Leave> пришёл из-за перехода на дочерний виджет,
# подсказку не скрываем.
_LEAVE_CHECK_DELAY_MS = 80

# Safety-polling: каждые N мс проверяем позицию указателя,
# пока тултип видим. Это устраняет «зависание», если <Leave>
# не дошёл или был отменён таймаут.
_POLL_INTERVAL_MS = 200

# Служебный цвет для прозрачных углов.
_TRANSPARENT_COLOR = "#ff00fe"

TooltipText = str | Callable[[], str]


# --- Глобальный трекер активной подсказки ---

_active_tooltip: Tooltip | None = None


def _register_active(tooltip: Tooltip) -> None:
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
    global _active_tooltip
    if _active_tooltip is tooltip:
        _active_tooltip = None


def _get_scaling(widget) -> float:
    try:
        value = ctk.ScalingTracker.get_widget_scaling(widget)
        if value and value > 0:
            return float(value)
    except Exception as exc:
        logger.debug("ScalingTracker.get_widget_scaling: %r", exc)
    return 1.0


def _make_transparent(window: tk.Toplevel) -> None:
    try:
        window.configure(bg=_TRANSPARENT_COLOR)
    except Exception as exc:
        logger.debug("configure(bg) у Toplevel: %r", exc)
        return

    try:
        window.attributes("-transparentcolor", _TRANSPARENT_COLOR)
    except Exception as exc:
        logger.debug("-transparentcolor: %r", exc)


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

        self._top: tk.Toplevel | None = None
        self._show_job: str | None = None
        self._leave_job: str | None = None
        self._poll_job: str | None = None

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
        self._schedule_leave_check()

    def _on_press(self, _event=None) -> None:
        self._cancel_jobs()
        self.hide()

    def _on_destroy(self, event=None) -> None:
        if event is not None and event.widget is not self._widget:
            return
        self.destroy()

    # --- Проверка «реально ли ушли» ---

    def _schedule_leave_check(self) -> None:
        if self._widget is None:
            return
        self._cancel_leave_job()
        try:
            self._leave_job = self._widget.after(
                _LEAVE_CHECK_DELAY_MS, self._check_leave,
            )
        except Exception as exc:
            logger.debug("after() при Leave tooltip: %r", exc)

    def _check_leave(self) -> None:
        self._leave_job = None
        if self._widget is None:
            return
        if self._is_pointer_inside():
            return
        self.hide()

    # --- Polling (safety net) ---

    def _schedule_poll(self) -> None:
        if self._widget is None:
            return
        if self._top is None:
            self._poll_job = None
            return
        self._cancel_poll_job()
        try:
            self._poll_job = self._widget.after(
                _POLL_INTERVAL_MS, self._on_poll_tick,
            )
        except Exception as exc:
            logger.debug("after() poll tooltip: %r", exc)

    def _on_poll_tick(self) -> None:
        self._poll_job = None
        if self._widget is None or self._top is None:
            return
        if not self._is_pointer_inside():
            logger.debug(
                "poll: указатель вне — скрываю tooltip",
            )
            self.hide()
            return
        self._schedule_poll()

    def _is_pointer_inside(self) -> bool:
        """Указатель на виджете или на самом tooltip?"""
        if self._widget is None:
            return False
        try:
            under = self._widget.winfo_containing(
                self._widget.winfo_pointerx(),
                self._widget.winfo_pointery(),
            )
        except Exception as exc:
            logger.debug("winfo_containing (poll): %r", exc)
            return False
        if under is None:
            return False
        return self._is_inside(under)

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
            # Гарантируем, что polling активен (мог быть
            # отменён между показами).
            if self._poll_job is None:
                self._schedule_poll()
            return

        text = self._resolve_text().strip()
        if not text:
            return

        try:
            top = tk.Toplevel(self._widget)
        except Exception as exc:
            logger.error("Не удалось создать окно tooltip: %r", exc)
            return

        # Создаём скрытым — показываем после полной настройки.
        try:
            top.withdraw()
        except Exception as exc:
            logger.debug("withdraw tooltip: %r", exc)

        try:
            top.overrideredirect(True)
        except Exception as exc:
            logger.debug("overrideredirect tooltip: %r", exc)

        try:
            top.attributes("-topmost", True)
        except Exception as exc:
            logger.debug("attributes(-topmost) у tooltip: %r", exc)

        _make_transparent(top)

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

        try:
            top.update_idletasks()
        except Exception as exc:
            logger.debug("update_idletasks tooltip: %r", exc)

        self._top = top
        self._position(top)

        try:
            top.deiconify()
            top.lift()
        except Exception as exc:
            logger.debug("deiconify/lift tooltip: %r", exc)

        _register_active(self)

        # Safety-polling: пока тултип видим — каждые 200 мс
        # проверяем, что указатель всё ещё на виджете или на
        # самом тултипе. Это заменяет прежний 10-секундный
        # таймаут, который мог быть отменён в _on_enter и
        # оставить тултип «зависшим».
        self._schedule_poll()

    def _resolve_text(self) -> str:
        if callable(self._text):
            try:
                return str(self._text())
            except Exception as exc:
                logger.debug(
                    "callable текста tooltip упал: %r", exc,
                )
                return ""
        return self._text or ""

    def _position(self, top: tk.Toplevel) -> None:
        try:
            wx = self._widget.winfo_rootx()
            wy = self._widget.winfo_rooty()
            wh = self._widget.winfo_height()
        except Exception as exc:
            logger.debug("геометрия виджета для tooltip: %r", exc)
            return

        try:
            tw = top.winfo_reqwidth()
            th = top.winfo_reqheight()
        except Exception as exc:
            logger.debug("reqsize tooltip: %r", exc)
            return

        if tw <= 1 or th <= 1:
            return

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

        try:
            top.geometry(f"+{x}+{y}")
        except Exception as exc:
            logger.debug("geometry tooltip: %r", exc)

    def _close_window(self) -> None:
        self._cancel_poll_job()
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

    def _cancel_poll_job(self) -> None:
        if self._poll_job is None or self._widget is None:
            return
        try:
            self._widget.after_cancel(self._poll_job)
        except Exception as exc:
            logger.debug("after_cancel poll tooltip: %r", exc)
        self._poll_job = None

    def _cancel_jobs(self) -> None:
        self._cancel_show_job()
        self._cancel_leave_job()
        # Polling НЕ отменяем: он управляется в _close_window и
        # _schedule_poll. Если отменить здесь, то _do_show при
        # early return (тултип уже виден) не запланирует его
        # заново — и тултип «зависнет».
