"""Статус-бар с прогрессом и кнопкой «Отмена».

Кнопка «Отмена» видна только во время активного копирования.
Управляется извне через show_cancel_button(show). Callback
устанавливается через set_on_cancel — MainWindow передаёт
свой метод cancel_copy.

Раскладка (слева направо):
  [status label — expand] ... [percent] [progress] [Отмена]
"""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from ui.components.button import (
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.fonts import get_font
from utils.logger import get_logger

logger = get_logger(__name__)

_FONT_SIZE = 12
_CANCEL_FONT_SIZE = 11

_CANCEL_BUTTON_WIDTH = 100
_CANCEL_BUTTON_HEIGHT = 24

_PROGRESS_WIDTH = 220
_PROGRESS_HEIGHT = 12

_STATUS_BAR_HEIGHT = 32


class StatusBar(ctk.CTkFrame):
    """Статус-бар: текст, прогресс, кнопка «Отмена»."""

    def __init__(self, master):
        super().__init__(
            master, height=_STATUS_BAR_HEIGHT, corner_radius=0,
        )
        self.grid_propagate(False)

        self._on_cancel: Callable[[], None] | None = None
        self._progress_visible = False
        self._cancel_visible = False

        # Текст статуса — занимает всё свободное место слева.
        self.label = ctk.CTkLabel(
            self, text="Готово", anchor="w",
            font=get_font(_FONT_SIZE),
        )
        self.label.pack(side="left", padx=12, fill="x", expand=True)

        # Кнопка «Отмена» — крайняя справа.
        self.cancel_button = StyledButton(
            self,
            text="Отмена",
            variant=VARIANT_SECONDARY,
            width=_CANCEL_BUTTON_WIDTH,
            height=_CANCEL_BUTTON_HEIGHT,
            command=self._handle_cancel_click,
        )
        try:
            self.cancel_button.configure(
                font=get_font(_CANCEL_FONT_SIZE),
            )
        except Exception as exc:
            logger.debug("configure шрифта кнопки: %r", exc)

        # Прогресс-бар и процент — левее кнопки, изначально скрыты.
        self.percent_label = ctk.CTkLabel(
            self, text="", anchor="e",
            font=get_font(_FONT_SIZE, "bold"),
        )
        self.progress = ctk.CTkProgressBar(
            self,
            width=_PROGRESS_WIDTH,
            height=_PROGRESS_HEIGHT,
        )
        self.progress.set(0.0)

    # --- Публичное API ---

    def set_text(self, text: str) -> None:
        self.label.configure(text=text)

    def set_on_cancel(self, callback: Callable[[], None]) -> None:
        """Устанавливает обработчик клика по «Отмена»."""
        self._on_cancel = callback

    def show_progress(self, value: float | None) -> None:
        """Показать / обновить / скрыть прогресс-бар.

        value=None — скрыть прогресс и процент.
        value=0.0..1.0 — показать и обновить.
        """
        if value is None:
            if self._progress_visible:
                self.progress.pack_forget()
                self.percent_label.pack_forget()
                self._progress_visible = False
            return

        if not self._progress_visible:
            # Порядок: сначала percent, потом progress — оба
            # pack(side="right"), поэтому percent оказывается
            # левее progress. Кнопка отмены, если видима, стоит
            # ещё левее.
            self.percent_label.pack(side="right", padx=(0, 8))
            self.progress.pack(side="right", padx=(0, 12))
            self._progress_visible = True

        v = max(0.0, min(1.0, float(value)))
        self.progress.set(v)
        self.percent_label.configure(text=f"{round(v * 100)}%")

    def show_cancel_button(self, show: bool) -> None:
        """Показать / скрыть кнопку «Отмена».

        Идемпотентно: повторный вызов с тем же значением ничего
        не делает.
        """
        if show == self._cancel_visible:
            return

        try:
            if show:
                self.cancel_button.pack(side="right", padx=(0, 12))
            else:
                self.cancel_button.pack_forget()
        except Exception as exc:
            logger.debug("pack кнопки отмены: %r", exc)
            return

        self._cancel_visible = show

    # --- Внутреннее ---

    def _handle_cancel_click(self) -> None:
        if self._on_cancel is None:
            return
        try:
            self._on_cancel()
        except Exception as exc:
            logger.error("Ошибка обработчика отмены: %r", exc)
