"""Кастомный выпадающий список в стиле CustomTkinter.

В отличие от CTkOptionMenu, попап отрисовывается как отдельный
CTkToplevel с overrideredirect — без системной рамки.
"""

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ui.components.popup_utils import get_scaling as _get_scaling
from ui.fonts import get_font
from ui.palette import (
    ACCENT,
    ACCENT_HOVER,
    DROPDOWN_HOVER,
    SURFACE_ACTIVE,
    SURFACE_BG,
    SURFACE_BORDER,
    SURFACE_RADIUS,
    SURFACE_TEXT,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_FONT_SIZE = 13
_DEFAULT_WIDTH = 220
_DEFAULT_HEIGHT = 32
_ITEM_HEIGHT = 32
_POPUP_PAD = 4
_POPUP_GAP = 4
_ARROW_WIDTH = 32
_ARROW_PAD = 3
_FOCUS_CHECK_DELAY_MS = 100

# Геометрия основной плашки: padx label (слева, справа) +
# зазор между label и arrow_button + arrow_button + её padx.
_LABEL_PADX_LEFT = 12
_LABEL_PADX_RIGHT = 4
_ARROW_EXTRA = 4


class StyledOptionMenu(ctk.CTkFrame):
    """Выпадающий список с кастомным попапом."""

    def __init__(
        self,
        master,
        *,
        values: list[str],
        variable: ctk.Variable | None = None,
        command: Callable[[str], None] | None = None,
        width: int = _DEFAULT_WIDTH,
        height: int = _DEFAULT_HEIGHT,
        auto_width: bool = False,
        min_width: int = 0,
        max_width: int | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            fg_color=SURFACE_BG,
            corner_radius=SURFACE_RADIUS,
            border_width=1,
            border_color=SURFACE_BORDER,
            **kwargs,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)

        self._values = list(values)
        self._auto_width = auto_width
        self._min_width = min_width
        self._max_width = max_width

        initial = self._values[0] if self._values else ""
        self._variable = variable or ctk.StringVar(value=initial)
        self._command = command
        self._popup: _DropdownPopup | None = None
        self._enabled = True

        self._label = ctk.CTkLabel(
            self,
            text=self._variable.get(),
            anchor="w",
            font=get_font(_DEFAULT_FONT_SIZE),
            text_color=SURFACE_TEXT,
        )
        self._label.pack(
            side="left", fill="both", expand=True,
            padx=(_LABEL_PADX_LEFT, _LABEL_PADX_RIGHT), pady=2,
        )

        self._build_arrow(height)

        self._label.bind("<Button-1>", lambda _e: self._toggle_popup())
        self.bind("<Button-1>", lambda _e: self._toggle_popup())

        self._variable.trace_add("write", self._on_variable_changed)

        if self._auto_width:
            self._fit_width()

    # --- Публичный API ---

    def set(self, value: str) -> None:
        self._variable.set(value)

    def get(self) -> str:
        return self._variable.get()

    def set_enabled(self, enabled: bool) -> None:
        """Блокирует/разблокирует выбор без смены внешнего вида."""
        self._enabled = bool(enabled)
        try:
            self._arrow_button.configure(
                state="normal" if enabled else "disabled",
            )
        except Exception as exc:
            logger.debug("option_menu set_enabled: %r", exc)

    def configure_values(self, values: list[str]) -> None:
        self._values = list(values)
        if self._auto_width:
            self._fit_width()

    def set_values(self, values: list[str]) -> None:
        self.configure_values(values)

    # --- Авто-ширина ---

    def _fit_width(self) -> None:
        font = get_font(_DEFAULT_FONT_SIZE)

        max_text_w = 0
        for value in self._values:
            w = self._measure_text(font, value)
            if w > max_text_w:
                max_text_w = w

        content_w = (
            max_text_w
            + _LABEL_PADX_LEFT
            + _LABEL_PADX_RIGHT
            + _ARROW_EXTRA
            + _ARROW_WIDTH
            + 2 * _ARROW_PAD
        )

        if content_w < self._min_width:
            content_w = self._min_width
        if self._max_width is not None and content_w > self._max_width:
            content_w = self._max_width

        try:
            self.configure(width=content_w)
        except Exception as exc:
            logger.debug(
                "не удалось установить ширину меню: %r", exc,
            )

    @staticmethod
    def _measure_text(font, text: str) -> int:
        try:
            return int(font.measure(text))
        except Exception as exc:
            logger.debug("font.measure не сработал: %r", exc)
            return len(text) * 8

    # --- Кнопка-стрелка ---

    def _build_arrow(self, frame_height: int) -> None:
        arrow_height = frame_height - 2 * _ARROW_PAD
        self._arrow_button = ctk.CTkButton(
            self,
            text="\u25BC",
            width=_ARROW_WIDTH,
            height=arrow_height,
            corner_radius=SURFACE_RADIUS,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="white",
            font=get_font(_DEFAULT_FONT_SIZE - 1),
            command=self._toggle_popup,
        )
        self._arrow_button.pack(
            side="right",
            padx=_ARROW_PAD,
            pady=_ARROW_PAD,
        )

    # --- Внутренняя логика ---

    def _on_variable_changed(self, *args) -> None:
        self._label.configure(text=self._variable.get())

    def _toggle_popup(self) -> None:
        if not getattr(self, "_enabled", True):
            return
        if self._popup is not None:
            self._popup.close()
        else:
            self._open_popup()

    def _open_popup(self) -> None:
        if not self._values:
            return
        self._popup = _DropdownPopup(
            master=self.winfo_toplevel(),
            anchor_widget=self,
            values=self._values,
            current=self.get(),
            on_select=self._on_select,
            on_close=self._on_popup_closed,
        )
        self._popup.open()

    def _on_popup_closed(self) -> None:
        self._popup = None

    def _on_select(self, value: str) -> None:
        self._variable.set(value)
        if self._command is not None:
            try:
                self._command(value)
            except Exception as exc:
                logger.error("ошибка command: %r", exc)


class _DropdownPopup:
    """Безрамочное всплывающее окно со списком пунктов."""

    def __init__(
        self,
        master,
        anchor_widget: ctk.CTkFrame,
        values: list[str],
        current: str,
        on_select: Callable[[str], None],
        on_close: Callable[[], None],
    ):
        self._master = master
        self._anchor = anchor_widget
        self._values = values
        self._current = current
        self._on_select = on_select
        self._on_close = on_close
        self._top: ctk.CTkToplevel | None = None
        self._focus_check_job: str | None = None

    def open(self) -> None:
        top = ctk.CTkToplevel(self._master)
        self._top = top
        top.overrideredirect(True)

        frame = ctk.CTkFrame(
            top,
            fg_color=SURFACE_BG,
            corner_radius=SURFACE_RADIUS,
            border_width=1,
            border_color=SURFACE_BORDER,
        )
        frame.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(
            fill="both", expand=True,
            padx=_POPUP_PAD, pady=_POPUP_PAD,
        )

        font = get_font(_DEFAULT_FONT_SIZE)
        for value in self._values:
            is_current = value == self._current
            btn = ctk.CTkButton(
                inner,
                text=value,
                anchor="w",
                height=_ITEM_HEIGHT,
                corner_radius=SURFACE_RADIUS,
                fg_color=SURFACE_ACTIVE if is_current else "transparent",
                hover_color=DROPDOWN_HOVER,
                text_color=SURFACE_TEXT,
                font=font,
                command=lambda v=value: self._select(v),
            )
            btn.pack(fill="x", pady=1)

        top.update_idletasks()

        # Всё в физических пикселях: winfo_* физические, а CTk-обёртка
        # geometry() умножила бы их ещё раз. Иначе на DPI > 100%
        # ширина (физическая) и высота (логическая) оказывались в
        # разных единицах и последний пункт обрезался.
        scaling = _get_scaling(top)
        width = max(self._anchor.winfo_width(), round(100 * scaling))
        height = round(
            (
                len(self._values) * (_ITEM_HEIGHT + 2)
                + 2 * _POPUP_PAD
            ) * scaling,
        )

        try:
            x = self._anchor.winfo_rootx()
            y = (
                self._anchor.winfo_rooty()
                + self._anchor.winfo_height()
                + round(_POPUP_GAP * scaling)
            )
        except Exception as exc:
            logger.error(
                "не удалось вычислить позицию попапа: %r", exc,
            )
            self.close()
            return

        top.wm_geometry(f"{width}x{height}+{x}+{y}")
        try:
            top.lift()
        except Exception as exc:
            logger.debug("lift попапа не удался: %r", exc)

        self._bind_global_handlers()
        top.bind("<Escape>", lambda _e: self.close())

    # --- Обработчики ---

    def _bind_global_handlers(self) -> None:
        try:
            self._master.bind_all(
                "<Button-1>", self._on_global_click, add="+",
            )
            self._master.bind(
                "<FocusOut>", self._on_master_focus_out, add="+",
            )
        except Exception as exc:
            logger.error(
                "не удалось повесить глобальные обработчики: %r", exc,
            )

    def _unbind_global_handlers(self) -> None:
        try:
            self._master.unbind_all("<Button-1>")
        except Exception as exc:
            logger.debug("unbind_all Button-1 не удался: %r", exc)
        try:
            self._master.unbind("<FocusOut>")
        except Exception as exc:
            logger.debug("unbind FocusOut не удался: %r", exc)

    def _on_global_click(self, event) -> None:
        if self._top is None:
            return
        if self._is_point_in_popup(event.x_root, event.y_root):
            return
        if self._is_point_in_widget(
            self._anchor, event.x_root, event.y_root,
        ):
            return
        self.close()

    def _on_master_focus_out(self, event) -> None:
        if self._top is None:
            return
        if self._focus_check_job is not None:
            return
        try:
            self._focus_check_job = self._master.after(
                _FOCUS_CHECK_DELAY_MS, self._check_app_focus,
            )
        except Exception as exc:
            logger.debug(
                "не удалось запланировать проверку фокуса: %r", exc,
            )

    def _check_app_focus(self) -> None:
        self._focus_check_job = None
        if self._top is None:
            return
        try:
            focused = self._master.focus_get()
        except Exception as exc:
            logger.debug("focus_get не удался: %r", exc)
            return
        if focused is None:
            logger.debug("приложение потеряло фокус — закрываю попап")
            self.close()

    # --- Проверки координат ---

    def _is_point_in_popup(self, x_root: int, y_root: int) -> bool:
        if self._top is None:
            return False
        return self._is_point_in_widget(self._top, x_root, y_root)

    @staticmethod
    def _is_point_in_widget(
        widget, x_root: int, y_root: int,
    ) -> bool:
        try:
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty()
            ww = widget.winfo_width()
            wh = widget.winfo_height()
        except Exception as exc:
            logger.debug(
                "не удалось получить геометрию виджета: %r", exc,
            )
            return False
        return wx <= x_root <= wx + ww and wy <= y_root <= wy + wh

    # --- Выбор и закрытие ---

    def _select(self, value: str) -> None:
        try:
            self._on_select(value)
        finally:
            self.close()

    def close(self) -> None:
        if self._top is None:
            return
        top = self._top
        self._top = None

        if self._focus_check_job is not None:
            try:
                self._master.after_cancel(self._focus_check_job)
            except Exception as exc:
                logger.debug(
                    "after_cancel проверки фокуса не удался: %r", exc,
                )
            self._focus_check_job = None

        self._unbind_global_handlers()

        try:
            top.destroy()
        except Exception as exc:
            logger.debug("destroy попапа не удался: %r", exc)

        try:
            self._on_close()
        except Exception as exc:
            logger.error("on_close попапа упал: %r", exc)
