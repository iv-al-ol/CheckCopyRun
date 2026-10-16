"""CTkScrollableFrame со скрывающейся полосой прокрутки."""

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger(__name__)

SETTLE_DELAY_MS = 100
IMMEDIATE_DELAY_MS = 20
MIN_TRUSTED_VIEW_H = 100

GHOST_BUTTON_COLOR = ("gray86", "gray17")
GHOST_BUTTON_HOVER = ("gray86", "gray17")


class AutoHideScrollableFrame(ctk.CTkScrollableFrame):
    """Полоса прокрутки визуально скрыта, когда скроллить нечего."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self._settle_job = None
        self._initialized = False
        self._ghosted: bool | None = None
        self._last_needs_scroll: bool | None = None

        scrollbar = getattr(self, "_scrollbar", None)

        self._real_button_color = ("gray70", "gray40")
        self._real_button_hover_color = ("gray60", "gray30")
        self._real_fg_color = "transparent"

        if scrollbar is not None:
            try:
                stored = scrollbar.cget("button_color")
                if stored:
                    self._real_button_color = stored
                stored_hover = scrollbar.cget("button_hover_color")
                if stored_hover:
                    self._real_button_hover_color = stored_hover
                stored_fg = scrollbar.cget("fg_color")
                if stored_fg is not None:
                    self._real_fg_color = stored_fg
            except Exception as exc:
                logger.debug(
                    "не удалось прочитать цвета полосы прокрутки: %r", exc,
                )

        self._apply_ghost(True)

        self._parent_canvas.bind(
            "<Configure>", self._on_configure, add="+",
        )

        self.after(SETTLE_DELAY_MS, self._initial_check)

    def check_scroll(self) -> None:
        self._schedule_settle(immediate=False)

    def check_scroll_now(self) -> None:
        self._schedule_settle(immediate=True)

    def refresh_ghost(self) -> None:
        self._ghosted = None
        self._last_needs_scroll = None
        self._update()

    def _apply_ghost(self, ghosted: bool) -> None:
        scrollbar = getattr(self, "_scrollbar", None)
        if scrollbar is None:
            self._ghosted = ghosted
            return
        if ghosted == self._ghosted:
            return
        try:
            if ghosted:
                scrollbar.configure(
                    button_color=GHOST_BUTTON_COLOR,
                    button_hover_color=GHOST_BUTTON_HOVER,
                    fg_color="transparent",
                )
            else:
                scrollbar.configure(
                    button_color=self._real_button_color,
                    button_hover_color=self._real_button_hover_color,
                    fg_color=self._real_fg_color,
                )
        except Exception as exc:
            logger.debug(
                "не удалось переключить вид полосы прокрутки: %r", exc,
            )
        self._ghosted = ghosted

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
        self._apply_ghost(not needs_scroll)
