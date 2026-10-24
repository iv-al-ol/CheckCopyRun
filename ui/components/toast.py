"""Всплывающее уведомление с плавным появлением и исчезновением.

Собственное окно вместо нативного Windows-toast: только Tk даёт
произвольную длительность показа и управляемую анимацию угасания
(`attributes("-alpha", …)`).

Особенности:
  • окно без рамки (`overrideredirect`), поверх остальных
    (`-topmost`), не забирает фокус;
  • показывается даже если главное окно свёрнуто в трей;
  • `auto_close_sec == 0` — уведомление висит, пока его не
    закроют кликом; иначе угасает через заданное время;
  • несколько уведомлений выстраиваются стопкой снизу вверх.

Работает только в главном потоке Tk: [`ToastNotifier`](ui/components/toast.py)
ставит показ в очередь через `after(0, …)`.
"""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from config.constants import (
    NOTIFY_FADE_IN_MS,
    NOTIFY_FADE_OUT_MS,
    NOTIFY_FADE_STEP_MS,
)
from services.system.notifier import Notification
from ui.dialogs._centering import get_scaling
from ui.fonts import get_font
from ui.palette import SURFACE_BG, SURFACE_BORDER, SURFACE_RADIUS
from utils.logger import get_logger

logger = get_logger(__name__)

_WIDTH = 360
_MIN_HEIGHT = 84
_MAX_HEIGHT = 320
_MARGIN_X = 20
_MARGIN_Y = 20
_STACK_GAP = 10

_TITLE_FONT_SIZE = 13
_BODY_FONT_SIZE = 12
_HINT_FONT_SIZE = 11
_PADDING = 14
_HINT_PADDING = 6

_CLOSE_HINT = "Клик — закрыть"

_ALPHA_STEP_TARGET = 60.0
_MIN_ALPHA = 0.0
_MAX_ALPHA = 0.96


class ToastWindow(ctk.CTkToplevel):
    """Одно всплывающее уведомление."""

    def __init__(
        self,
        master,
        notification: Notification,
        *,
        offset_index: int = 0,
        on_closed=None,
    ):
        super().__init__(master)

        self._notification = notification
        self._offset_index = offset_index
        self._on_closed = on_closed
        self._closing = False
        self._alpha = _MIN_ALPHA
        self._jobs: list[str] = []

        self.withdraw()
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except Exception as exc:
            logger.debug("toast -topmost: %r", exc)
        self._set_alpha(_MIN_ALPHA)

        self._build()

        self.bind("<Button-1>", lambda _e: self.dismiss())
        for child in self.winfo_children():
            child.bind("<Button-1>", lambda _e: self.dismiss())

        self.update_idletasks()
        self._position()
        self.deiconify()
        self._fade_in()

    # --- Построение ---

    def _build(self) -> None:
        self.configure(fg_color=SURFACE_BG)
        self.grid_columnconfigure(0, weight=1)

        frame = ctk.CTkFrame(
            self,
            fg_color=SURFACE_BG,
            border_width=1,
            border_color=SURFACE_BORDER,
            corner_radius=SURFACE_RADIUS,
        )
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(
            frame,
            text=self._notification.title,
            anchor="w",
            justify="left",
            font=get_font(_TITLE_FONT_SIZE, "bold"),
        ).grid(
            row=0, column=0, sticky="ew",
            padx=(_PADDING, _PADDING),
            pady=(_PADDING, 4),
        )

        body = ctk.CTkLabel(
            frame,
            text=self._notification.body,
            anchor="w",
            justify="left",
            wraplength=self._wrap_length(),
            font=get_font(_BODY_FONT_SIZE),
        )
        body.grid(
            row=1, column=0, sticky="ew",
            padx=(_PADDING, _PADDING),
        )

        hint = ctk.CTkLabel(
            frame,
            text=_CLOSE_HINT,
            anchor="w",
            text_color=("gray45", "gray55"),
            font=get_font(_HINT_FONT_SIZE),
        )
        hint.grid(
            row=2, column=0, sticky="w",
            padx=(_PADDING, _PADDING),
            pady=(_HINT_PADDING, _PADDING),
        )

    def _wrap_length(self) -> int:
        scaling = get_scaling(self) or 1.0
        return int((_WIDTH - 2 * _PADDING - 8) * scaling)

    def _measure_height(self) -> int:
        """Высота по содержимому, с ограничением диапазона."""
        try:
            self.update_idletasks()
            needed = int(self.winfo_reqheight())
        except Exception as exc:
            logger.debug("toast reqheight: %r", exc)
            needed = _MIN_HEIGHT
        return max(_MIN_HEIGHT, min(_MAX_HEIGHT, needed))

    # --- Геометрия ---

    def _position(self) -> None:
        """Правый нижний угол рабочей области, стопкой вверх."""
        scaling = get_scaling(self) or 1.0
        try:
            screen_w = int(self.winfo_screenwidth())
            screen_h = int(self.winfo_screenheight())
        except Exception as exc:
            logger.debug("toast screen size: %r", exc)
            return

        width = int(_WIDTH * scaling)
        height = self._measure_height()

        x = screen_w - width - int(_MARGIN_X * scaling)
        y = (
            screen_h
            - height
            - int((_MARGIN_Y + _STACK_GAP * self._offset_index)
                  * scaling)
        )

        try:
            self.wm_geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        except Exception as exc:
            logger.error("toast wm_geometry: %r", exc)

    # --- Анимация ---

    def _set_alpha(self, value: float) -> None:
        self._alpha = max(_MIN_ALPHA, min(_MAX_ALPHA, value))
        try:
            self.attributes("-alpha", self._alpha)
        except Exception as exc:
            logger.debug("toast -alpha: %r", exc)

    def _fade_in(self) -> None:
        self._animate(
            start=_MIN_ALPHA,
            end=_MAX_ALPHA,
            duration_ms=NOTIFY_FADE_IN_MS,
            on_done=self._schedule_auto_close,
        )

    def dismiss(self) -> None:
        """Плавно закрывает уведомление."""
        if self._closing:
            return
        self._closing = True
        self._cancel_jobs()
        self._animate(
            start=self._alpha,
            end=_MIN_ALPHA,
            duration_ms=NOTIFY_FADE_OUT_MS,
            on_done=self._destroy,
        )

    def _schedule_auto_close(self) -> None:
        auto_close = int(self._notification.auto_close_sec or 0)
        if auto_close <= 0:
            return
        job = self.after(auto_close * 1000, self.dismiss)
        self._jobs.append(job)

    def _animate(
        self,
        *,
        start: float,
        end: float,
        duration_ms: int,
        on_done,
    ) -> None:
        """Линейное изменение прозрачности за `duration_ms`."""
        steps = max(1, int(duration_ms / NOTIFY_FADE_STEP_MS))
        step_delta = (end - start) / steps
        value = start
        self._set_alpha(value)

        for index in range(1, steps + 1):
            alpha = start + step_delta * index
            delay = NOTIFY_FADE_STEP_MS * index
            job = self.after(
                delay,
                lambda a=alpha: self._set_alpha(a),
            )
            self._jobs.append(job)

        job = self.after(duration_ms, on_done)
        self._jobs.append(job)

    def _cancel_jobs(self) -> None:
        for job in self._jobs:
            try:
                self.after_cancel(job)
            except Exception as exc:
                logger.debug("toast after_cancel: %r", exc)
        self._jobs.clear()

    def _destroy(self) -> None:
        try:
            self.grab_release()
        except Exception as exc:
            logger.debug("toast grab_release: %r", exc)
        try:
            self.destroy()
        except Exception as exc:
            logger.debug("toast destroy: %r", exc)
        if self._on_closed is not None:
            try:
                self._on_closed(self)
            except Exception as exc:
                logger.error(
                    "toast on_closed: %r", exc, exc_info=True,
                )


class ToastManager:
    """Показывает уведомления стопкой и следит за жизненным циклом."""

    def __init__(self, master: Any):
        self._master = master
        self._active: list[ToastWindow] = []

    def show(self, notification: Notification) -> bool:
        """Показывает уведомление. Вызывать только в Tk-потоке."""
        try:
            window = ToastWindow(
                self._master,
                notification,
                offset_index=len(self._active),
                on_closed=self._on_closed,
            )
        except Exception as exc:
            logger.error(
                "ToastManager: не удалось показать: %r",
                exc, exc_info=True,
            )
            return False

        self._active.append(window)
        return True

    def _on_closed(self, window: ToastWindow) -> None:
        if window in self._active:
            self._active.remove(window)

    def close_all(self) -> None:
        for window in list(self._active):
            window.dismiss()


class ToastNotifier:
    """Адаптер `ToastManager` под протокол `Notifier`.

    Вызывается из фонового потока мониторинга, поэтому показ
    маршалится в главный поток через `after(0, …)`.
    """

    def __init__(self, manager: ToastManager, window):
        self._manager = manager
        self._window = window

    def notify(self, notification: Notification) -> bool:
        try:
            self._window.after(
                0,
                lambda n=notification: self._manager.show(n),
            )
        except Exception as exc:
            logger.error(
                "ToastNotifier: постановка в очередь: %r",
                exc, exc_info=True,
            )
            return False
        return True
