"""Пункт сайдбара: иконка + текст + опциональная кнопка запуска.

Поддерживает:
  • active (открыт в основной панели);
  • selected (выделен мышью для массовых действий);
  • hover.

Приоритет фона: selected > active > hover > default.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from config.constants import SIDEBAR_ITEM_HEIGHT
from ui.components.nav_icon import NavIcon
from ui.components.tooltip import Tooltip
from ui.fonts import get_font
from ui.palette import SUCCESS, SUCCESS_HOVER, SUCCESS_TEXT
from utils.logger import get_logger

logger = get_logger(__name__)


# --- Цвета навигации ---

NAV_BG = ("gray90", "gray17")
NAV_HOVER = ("gray80", "gray25")
NAV_ACTIVE = ("gray70", "gray30")
NAV_SELECTED = ("#b8cce0", "#3a4d5e")
NAV_TEXT = ("gray10", "gray90")

# --- Геометрия ---

_ITEM_RADIUS = 8
_ICON_SIZE = 28
_ICON_PADX_LEFT = 8
_ICON_PADX_RIGHT = 4
_TEXT_PADX_RIGHT = 8

_RUN_BUTTON_WIDTH = 28
_RUN_BUTTON_PADX = 6
_RUN_BUTTON_FONT_SIZE = 11

_FONT_SIZE = 13
_EMOJI_FONT_SIZE = 14

_RUN_TOOLTIP_DELAY_MS = 400


class NavItem(ctk.CTkFrame):
    """Пункт сайдбара: иконка + текст + опциональная кнопка запуска."""

    def __init__(
        self,
        master,
        *,
        icon: str,
        text: str,
        on_click: Callable[[tk.Event], None],
        on_context: Callable[[tk.Event], None] | None = None,
        on_run: Callable[[], None] | None = None,
        run_tooltip: str | None = None,
        bold: bool = False,
    ):
        super().__init__(
            master,
            fg_color=NAV_BG,
            corner_radius=_ITEM_RADIUS,
            height=SIDEBAR_ITEM_HEIGHT,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._on_click_cb = on_click
        self._active = False
        self._selected = False
        self._hover = False
        self._run_tooltip: Tooltip | None = None

        # --- Иконка ---
        self._icon_view = NavIcon(
            self,
            size=_ICON_SIZE,
            emoji_font_size=_EMOJI_FONT_SIZE,
            text_color=NAV_TEXT,
        )
        self._icon_view.grid(
            row=0, column=0,
            padx=(_ICON_PADX_LEFT, _ICON_PADX_RIGHT),
        )
        self._icon_view.set_icon(icon)

        # --- Текст ---
        self._text_label = ctk.CTkLabel(
            self,
            text=text,
            anchor="w",
            justify="left",
            text_color=NAV_TEXT,
            font=get_font(_FONT_SIZE, "bold" if bold else "normal"),
        )
        self._text_label.grid(
            row=0, column=1, sticky="ew",
            padx=(0, _TEXT_PADX_RIGHT),
        )

        # --- Кнопка запуска (опционально) ---
        self._run_button: ctk.CTkButton | None = None
        if on_run is not None:
            self._run_button = ctk.CTkButton(
                self,
                text="▶",
                width=_RUN_BUTTON_WIDTH,
                height=SIDEBAR_ITEM_HEIGHT - 10,
                corner_radius=6,
                font=get_font(_RUN_BUTTON_FONT_SIZE),
                command=on_run,
                fg_color=SUCCESS,
                hover_color=SUCCESS_HOVER,
                text_color=SUCCESS_TEXT,
            )
            self._run_button.grid(
                row=0, column=2, padx=(0, _RUN_BUTTON_PADX),
            )
            if run_tooltip:
                self._run_tooltip = Tooltip(
                    self._run_button,
                    run_tooltip,
                    delay_ms=_RUN_TOOLTIP_DELAY_MS,
                )

        # --- Биндинги ---
        targets: list = [
            self,
            *self._icon_view.get_bindable_widgets(),
            self._text_label,
        ]
        for w in targets:
            w.bind("<Button-1>", self._handle_click, add="+")
            w.bind("<Button-3>", self._handle_context, add="+")
            w.bind("<Enter>", self._handle_enter, add="+")
            w.bind("<Leave>", self._handle_leave, add="+")

    # --- Публичное ---

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self._apply_bg()

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self._apply_bg()

    # --- Обработчики ---

    def _handle_click(self, event) -> None:
        try:
            self._on_click_cb(event)
        except Exception as exc:
            logger.error("Ошибка клика пункта: %r", exc)

    def _handle_context(self, event) -> None:
        # ПКМ: если обработчик не задан — ничего не делаем,
        # иначе передаём event наверх (для модификаторов и
        # координат).
        cb = getattr(self, "_on_context_cb", None)
        if cb is None:
            return
        try:
            cb(event)
        except Exception as exc:
            logger.error(
                "Ошибка контекстного клика пункта: %r", exc,
            )

    def _handle_enter(self, _event=None) -> None:
        if not self._hover:
            self._hover = True
            self._apply_bg()

    def _handle_leave(self, _event=None) -> None:
        try:
            self.after(20, self._check_hover)
        except Exception as exc:
            logger.debug("after() при Leave: %r", exc)

    def _check_hover(self) -> None:
        try:
            under = self.winfo_containing(
                self.winfo_pointerx(), self.winfo_pointery(),
            )
        except Exception as exc:
            logger.debug("winfo_containing: %r", exc)
            return
        if under is None or not self._is_inside(under):
            if self._hover:
                self._hover = False
                self._apply_bg()

    def _is_inside(self, widget) -> bool:
        current = widget
        while current is not None:
            if current is self:
                return True
            current = getattr(current, "master", None)
        return False

    def _apply_bg(self) -> None:
        if self._selected:
            color = NAV_SELECTED
        elif self._active:
            color = NAV_ACTIVE
        elif self._hover:
            color = NAV_HOVER
        else:
            color = NAV_BG
        try:
            self.configure(fg_color=color)
        except Exception as exc:
            logger.debug("configure(fg_color): %r", exc)

    # --- Совместимость со старым API on_context ---

    def set_on_context(
        self, cb: Callable[[tk.Event], None] | None,
    ) -> None:
        """Установить обработчик ПКМ (после конструктора)."""
        self._on_context_cb = cb
