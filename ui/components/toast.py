"""Всплывающее уведомление с плавным появлением и исчезновением.

Собственное окно вместо нативного Windows-toast: только Tk даёт
произвольную длительность показа и управляемую анимацию угасания
(`attributes("-alpha", …)`).

Особенности:
  • окно без рамки (`overrideredirect`), поверх остальных
    (`-topmost`), не забирает фокус;
  • показывается даже если главное окно свёрнуто в трей;
  • `auto_close_sec == 0` — уведомление висит, пока его не
    закроют; иначе угасает через заданное время;
  • несколько уведомлений выстраиваются стопкой снизу вверх —
    без перекрытий. Позиции пересчитываются при каждом
    появлении и закрытии;
  • стопка прижата к рабочей области монитора (без панели
    задач) — WinAPI SPI_GETWORKAREA через
    `ui.window_geometry.get_work_area_logical`;
  • одновременно не более `NOTIFY_MAX_ACTIVE_TOASTS` окон;
  • кнопки «Открыть» (если `Notification.open_path` задан) и
    «Закрыть». «Открыть» использует
    `services.system.file_opener.open_file_with_fallback`
    (ассоциация → Блокнот → Проводник); при полном провале
    показывает диалог с путём и закрывает тост. «Закрыть» —
    просто закрывает. Клик по телу уведомления (вне кнопок)
    тоже закрывает.

Работает только в главном потоке Tk: `ToastNotifier` ставит
показ в очередь через `after(0, …)`.
"""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from config.constants import (
    NOTIFY_FADE_IN_MS,
    NOTIFY_FADE_OUT_MS,
    NOTIFY_FADE_STEP_MS,
    NOTIFY_MAX_ACTIVE_TOASTS,
)
from services.system.file_opener import open_file_with_fallback
from services.system.notifier import Notification
from ui.components.button import (
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.dialogs import show_error
from ui.fonts import get_font
from ui.palette import SURFACE_BG, SURFACE_BORDER, SURFACE_RADIUS
from ui.window_geometry import (
    get_dpi_scaling,
    get_work_area_logical,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Логические пиксели.
_WIDTH = 360
_MIN_HEIGHT = 84
_MAX_HEIGHT = 320
_MARGIN_X = 20
_MARGIN_Y = 20
_STACK_GAP = 10

_MAX_ACTIVE_TOASTS = NOTIFY_MAX_ACTIVE_TOASTS

_TITLE_FONT_SIZE = 13
_BODY_FONT_SIZE = 12
_BUTTON_FONT_SIZE = 11
_PADDING = 14
_BUTTON_GAP = 6

_BUTTON_WIDTH = 90
_BUTTON_HEIGHT = 26

_MIN_ALPHA = 0.0
_MAX_ALPHA = 0.96


class ToastWindow(ctk.CTkToplevel):
    """Одно всплывающее уведомление."""

    def __init__(
        self,
        master,
        notification: Notification,
        *,
        on_closed=None,
    ):
        super().__init__(master)

        self._notification = notification
        self._on_closed = on_closed
        self._closing = False
        self._alpha = _MIN_ALPHA
        self._jobs: list[str] = []

        # Масштаб фиксируем один раз в конструкторе: у тоста
        # он не меняется за время жизни.
        self._scaling = get_dpi_scaling(self) or 1.0

        # Высота в физических пикселях — её использует менеджер
        # для расчёта отступа снизу. Обновляется после постройки.
        self._height_physical = int(
            _MIN_HEIGHT * self._scaling
        )

        # Отступ от низа рабочей области в физических пикселях.
        # Ставит менеджер через set_bottom_offset_physical().
        self._y_bottom_offset_phys = 0

        self.withdraw()
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except Exception as exc:
            logger.debug("toast -topmost: %r", exc)
        self._set_alpha(_MIN_ALPHA)

        self._build()
        self._bind_body_click()

        self.update_idletasks()
        self._height_physical = self._measure_height_physical()

    # --- Публичное ---

    @property
    def height_physical(self) -> int:
        return self._height_physical

    @property
    def scaling(self) -> float:
        return self._scaling

    def set_bottom_offset_physical(self, offset_phys: int) -> None:
        """Отступ от низа рабочей области (физические px)."""
        self._y_bottom_offset_phys = int(offset_phys)
        self._position()

    def present(self) -> None:
        """Показать окно и запустить анимацию появления.

        Позицию менеджер уже выставил через
        set_bottom_offset_physical — здесь только deiconify
        и fade-in.
        """
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

        self._title_label = ctk.CTkLabel(
            frame,
            text=self._notification.title,
            anchor="w",
            justify="left",
            font=get_font(_TITLE_FONT_SIZE, "bold"),
        )
        self._title_label.grid(
            row=0, column=0, sticky="ew",
            padx=(_PADDING, _PADDING),
            pady=(_PADDING, 4),
        )

        self._body_label = ctk.CTkLabel(
            frame,
            text=self._notification.body,
            anchor="w",
            justify="left",
            wraplength=self._wrap_length(),
            font=get_font(_BODY_FONT_SIZE),
        )
        self._body_label.grid(
            row=1, column=0, sticky="ew",
            padx=(_PADDING, _PADDING),
        )

        btns_box = ctk.CTkFrame(frame, fg_color="transparent")
        btns_box.grid(
            row=2, column=0, sticky="e",
            padx=(_PADDING, _PADDING),
            pady=(8, _PADDING),
        )

        if self._notification.open_path:
            self._open_btn = StyledButton(
                btns_box,
                text="Открыть",
                variant=VARIANT_PRIMARY,
                width=_BUTTON_WIDTH,
                height=_BUTTON_HEIGHT,
                font=get_font(_BUTTON_FONT_SIZE),
                command=self._on_open,
            )
            self._open_btn.pack(
                side="left", padx=(0, _BUTTON_GAP),
            )

        self._close_btn = StyledButton(
            btns_box,
            text="Закрыть",
            variant=VARIANT_SECONDARY,
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
            font=get_font(_BUTTON_FONT_SIZE),
            command=self.dismiss,
        )
        self._close_btn.pack(side="left")

        self._body_widgets = [
            frame,
            self._title_label,
            self._body_label,
        ]

    def _bind_body_click(self) -> None:
        for widget in self._body_widgets:
            widget.bind(
                "<Button-1>",
                lambda _e: self.dismiss(),
                add="+",
            )

    def _wrap_length(self) -> int:
        return int(
            (_WIDTH - 2 * _PADDING - 8) * self._scaling,
        )

    def _measure_height_physical(self) -> int:
        """Фактическая высота в физических пикселях (с клампом)."""
        try:
            self.update_idletasks()
            needed = int(self.winfo_reqheight())
        except Exception as exc:
            logger.debug("toast reqheight: %r", exc)
            needed = int(_MIN_HEIGHT * self._scaling)

        min_phys = int(_MIN_HEIGHT * self._scaling)
        max_phys = int(_MAX_HEIGHT * self._scaling)
        if needed < min_phys:
            needed = min_phys
        if needed > max_phys:
            needed = max_phys
        return needed

    # --- Геометрия ---

    def _position(self) -> None:
        """Позиция: правый нижний угол рабочей области, стопкой."""
        scaling = self._scaling
        work = get_work_area_logical(self)
        if work is not None:
            screen_w_phys = int(work[0] * scaling)
            screen_h_phys = int(work[1] * scaling)
        else:
            try:
                screen_w_phys = int(self.winfo_screenwidth())
                screen_h_phys = int(self.winfo_screenheight())
            except Exception as exc:
                logger.debug("toast screen size: %r", exc)
                return

        width_phys = round(_WIDTH * scaling)
        x_phys = (
            screen_w_phys - width_phys
            - round(_MARGIN_X * scaling)
        )
        y_phys = (
            screen_h_phys
            - self._height_physical
            - round(_MARGIN_Y * scaling)
            - self._y_bottom_offset_phys
        )

        try:
            self.wm_geometry(
                f"{width_phys}x{self._height_physical}"
                f"+{max(0, x_phys)}+{max(0, y_phys)}"
            )
        except Exception as exc:
            logger.error("toast wm_geometry: %r", exc)

    # --- Действия ---

    def _on_open(self) -> None:
        """Открывает файл из `open_path`, закрывает тост.

        Цепочка способов — в `services.system.file_opener`
        (ассоциация → Блокнот → Проводник). Если ни один не
        сработал, показываем модальный диалог с путём — чтобы
        пользователь мог скопировать и открыть вручную. Тост
        закрываем в любом случае: пользователь уже нажал
        кнопку, держать её на экране — хуже.
        """
        path = self._notification.open_path
        if not path:
            self.dismiss()
            return

        result = open_file_with_fallback(path)
        if not result.success:
            show_error(
                self.master,
                "Не удалось открыть файл",
                result.error,
            )

        self.dismiss()

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
    """Показывает уведомления стопкой, следит за лимитом и порядком."""

    def __init__(self, master: Any):
        self._master = master
        self._active: list[ToastWindow] = []

    def show(self, notification: Notification) -> bool:
        """Показывает уведомление. Вызывать только в Tk-потоке."""
        try:
            window = ToastWindow(
                self._master,
                notification,
                on_closed=self._on_closed,
            )
        except Exception as exc:
            logger.error(
                "ToastManager: не удалось показать: %r",
                exc, exc_info=True,
            )
            return False

        while len(self._active) >= _MAX_ACTIVE_TOASTS:
            oldest = self._active.pop(0)
            try:
                oldest.dismiss()
            except Exception as exc:
                logger.debug(
                    "ToastManager: dismiss старого: %r", exc,
                )

        self._active.append(window)
        self._restack()
        window.present()
        return True

    def close_all(self) -> None:
        for window in list(self._active):
            window.dismiss()

    # --- Внутреннее ---

    def _restack(self) -> None:
        """Пересчитывает позиции стопки снизу вверх."""
        offset_phys = 0
        for window in self._active:
            window.set_bottom_offset_physical(offset_phys)
            gap_phys = round(_STACK_GAP * window.scaling)
            offset_phys += window.height_physical + gap_phys

    def _on_closed(self, window: ToastWindow) -> None:
        if window in self._active:
            self._active.remove(window)
            self._restack()


class ToastNotifier:
    """Адаптер `ToastManager` под протокол `Notifier`."""

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
