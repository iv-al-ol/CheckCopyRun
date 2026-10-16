"""CTkScrollableFrame со скрывающейся полосой прокрутки.

Стратегия скрытия: вместо перекраски в цвет фона полоса полностью
изымается из раскладки (grid_remove / pack_forget). Это надёжнее
маскировки — при смене темы и любом DPI полоса не «просвечивает».

Когда контент снова превышает видимую область — полоса возвращается
тем же grid()/pack() без параметров: tkinter восстановит её по
предыдущей позиции.
"""

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger(__name__)

SETTLE_DELAY_MS = 100
IMMEDIATE_DELAY_MS = 20
MIN_TRUSTED_VIEW_H = 100

# Несколько отложенных перепроверок при инициализации — canvas
# успевает растянуться по мере создания окна, и не всегда это
# происходит к моменту первой проверки.
_INITIAL_CHECKS_MS = (50, 150, 400)


class AutoHideScrollableFrame(ctk.CTkScrollableFrame):
    """Полоса прокрутки полностью скрыта, когда скроллить нечего."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self._settle_job: str | None = None
        self._initialized = False
        self._hidden: bool | None = None
        self._last_needs_scroll: bool | None = None

        scrollbar = getattr(self, "_scrollbar", None)
        if scrollbar is None:
            logger.debug(
                "AutoHideScrollableFrame: _scrollbar не найден, "
                "автоскрытие работать не будет",
            )

        # Изначально считаем, что скроллить нечего — прячем полосу.
        self._set_scrollbar_hidden(True)

        self._parent_canvas.bind(
            "<Configure>", self._on_configure, add="+",
        )

        for delay in _INITIAL_CHECKS_MS:
            self.after(delay, self._initial_check)

    # --- Публичное API ---

    def check_scroll(self) -> None:
        self._schedule_settle(immediate=False)

    def check_scroll_now(self) -> None:
        self._schedule_settle(immediate=True)

    def refresh_ghost(self) -> None:
        """Сбросить состояние — принудительная перепроверка."""
        self._hidden = None
        self._last_needs_scroll = None
        self._update()

    # --- Управление видимостью ---

    def _set_scrollbar_hidden(self, hidden: bool) -> None:
        """Скрывает/показывает полосу через grid_remove/pack_forget."""
        if hidden == self._hidden:
            return

        scrollbar = getattr(self, "_scrollbar", None)
        if scrollbar is None:
            self._hidden = hidden
            return

        if hidden:
            self._hide_scrollbar(scrollbar)
        else:
            self._show_scrollbar(scrollbar)

        self._hidden = hidden

    @staticmethod
    def _hide_scrollbar(scrollbar) -> None:
        # Пробуем grid_remove, затем pack_forget.
        try:
            if scrollbar.grid_info():
                scrollbar.grid_remove()
                return
        except Exception as exc:
            logger.debug("grid_info/grid_remove скроллбара: %r", exc)

        try:
            if scrollbar.pack_info():
                scrollbar.pack_forget()
                return
        except Exception as exc:
            logger.debug("pack_info/pack_forget скроллбара: %r", exc)

    @staticmethod
    def _show_scrollbar(scrollbar) -> None:
        # Восстанавливаем по последней позиции (без параметров).
        try:
            scrollbar.grid()
            return
        except Exception as exc:
            logger.debug("grid() скроллбара: %r", exc)

        try:
            scrollbar.pack()
        except Exception as exc:
            logger.debug("pack() скроллбара: %r", exc)

    # --- Жизненный цикл проверок ---

    def _initial_check(self) -> None:
        self._initialized = True
        self._update()

    def _on_configure(self, event=None) -> None:
        self._schedule_settle(immediate=False)

    def _schedule_settle(self, immediate: bool) -> None:
        if self._settle_job is not None:
            try:
                self.after_cancel(self._settle_job)
            except Exception as exc:
                logger.debug("after_cancel не удался: %r", exc)
        delay = IMMEDIATE_DELAY_MS if immediate else SETTLE_DELAY_MS
        self._settle_job = self.after(delay, self._settle_check)

    def _settle_check(self) -> None:
        self._settle_job = None
        if not self._initialized:
            return
        self._update()

    def _is_canvas_visible(self) -> bool:
        canvas = self._parent_canvas
        try:
            if not canvas.winfo_ismapped():
                return False
            if not self.winfo_toplevel().winfo_ismapped():
                return False
        except Exception as exc:
            logger.debug("winfo_ismapped не удался: %r", exc)
            return False
        return True

    def _update(self) -> None:
        if not self._is_canvas_visible():
            return

        canvas = self._parent_canvas
        try:
            content_h = self.winfo_reqheight()
            view_h = canvas.winfo_height()
        except Exception as exc:
            logger.debug("не удалось измерить canvas: %r", exc)
            return

        if view_h < MIN_TRUSTED_VIEW_H or content_h <= 1:
            return

        needs_scroll = content_h > view_h + 2
        if needs_scroll == self._last_needs_scroll:
            return
        self._last_needs_scroll = needs_scroll
        self._set_scrollbar_hidden(not needs_scroll)
