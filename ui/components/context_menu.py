"""Контекстное меню в стиле CustomTkinter.

Оформление повторяет StyledOptionMenu: плашка SURFACE_BG с тонкой
рамкой SURFACE_BORDER. Каждая строка — фикс-обёртка иконки 24×24
плюс текстовый label.

Скругления: окно прямоугольное, углы вне скруглённой рамки
заполняются служебным цветом и становятся прозрачными через
-transparentcolor (Windows).

Разделитель — ui.components.separator.make_separator.

Меню закрывается по:
- клику ЛКМ вне меню;
- клику ПКМ вне меню;
- потере фокуса приложением;
- Escape;
- выбору пункта.

Сам правый клик, открывший меню, не должен его закрывать:
bind Button-3 откладывается через after_idle, чтобы попасть
в следующий цикл событий (текущее событие ещё обрабатывается,
когда меню только создаётся).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from ui.components.popup_utils import (
    get_scaling as _get_scaling,
)
from ui.components.popup_utils import (
    is_inside as _widget_is_inside,
)
from ui.components.popup_utils import (
    make_transparent as _make_transparent,
)
from ui.components.separator import make_separator
from ui.fonts import get_emoji_font, get_font
from ui.palette import (
    DANGER_HOVER,
    DANGER_LABEL,
    DANGER_TEXT,
    SURFACE_BG,
    SURFACE_BORDER,
    SURFACE_HOVER,
    SURFACE_RADIUS,
    SURFACE_TEXT,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# --- Геометрия строки ---
_ITEM_HEIGHT = 34
_ITEM_PADY = 2
_FRAME_PAD = 4
_MIN_WIDTH = 210

_ICON_WRAPPER_SIZE = 24
_ICON_PADX_LEFT = 8
_ICON_PADX_RIGHT = 6
_TEXT_PADX_RIGHT = 12

_FONT_SIZE = 13
_EMOJI_FONT_SIZE = 13

_SEPARATOR_PADX = 10
_SEPARATOR_PADY = 4

_CURSOR_OFFSET = 4
_SCREEN_MARGIN = 8

_FOCUS_CHECK_DELAY_MS = 60

_FRAME_BORDER_WIDTH = 1



class _MenuRow(ctk.CTkFrame):
    """Строка меню: [обёртка иконки] [текст]. Всё по центру."""

    def __init__(
        self,
        master,
        *,
        icon: str,
        text: str,
        command: Callable[[], None],
        danger: bool = False,
    ):
        super().__init__(
            master,
            fg_color="transparent",
            corner_radius=SURFACE_RADIUS,
            height=_ITEM_HEIGHT,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._command = command
        self._danger = danger
        self._hover = False

        # Опасный пункт в покое — приглушённо-красный: белый на
        # светлой поверхности меню не читается. При наведении фон
        # становится тёмно-красным, и текст переключается на белый.
        text_color = DANGER_LABEL if danger else SURFACE_TEXT
        self._idle_text_color = text_color
        self._hover_text_color = DANGER_TEXT if danger else SURFACE_TEXT

        icon_wrapper = ctk.CTkFrame(
            self,
            fg_color="transparent",
            width=_ICON_WRAPPER_SIZE,
            height=_ICON_WRAPPER_SIZE,
        )
        icon_wrapper.grid_propagate(False)
        icon_wrapper.grid(
            row=0, column=0,
            padx=(_ICON_PADX_LEFT, _ICON_PADX_RIGHT),
        )

        icon_label: ctk.CTkLabel | None = None
        if icon:
            icon_label = ctk.CTkLabel(
                icon_wrapper,
                text=icon,
                anchor="center",
                text_color=text_color,
                font=get_emoji_font(_EMOJI_FONT_SIZE),
            )
            icon_label.pack(fill="both", expand=True)
        self._icon_label = icon_label

        self._text_label = ctk.CTkLabel(
            self,
            text=text,
            anchor="w",
            text_color=text_color,
            font=get_font(_FONT_SIZE),
        )
        self._text_label.grid(
            row=0, column=1, sticky="ew",
            padx=(0, _TEXT_PADX_RIGHT),
        )

        targets = [self, icon_wrapper]
        if icon_label is not None:
            targets.append(icon_label)
        targets.append(self._text_label)

        for w in targets:
            w.bind("<Button-1>", self._on_click, add="+")
            w.bind("<Enter>", self._on_enter, add="+")
            w.bind("<Leave>", self._on_leave, add="+")

    def _on_click(self, _event=None) -> None:
        try:
            self._command()
        except Exception as exc:
            logger.error(
                "Ошибка команды контекстного меню: %r", exc,
            )

    def _on_enter(self, _event=None) -> None:
        if not self._hover:
            self._hover = True
            self._apply_bg()

    def _on_leave(self, _event=None) -> None:
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
        return _widget_is_inside(widget, self)

    def _apply_bg(self) -> None:
        if self._hover:
            color = DANGER_HOVER if self._danger else SURFACE_HOVER
        else:
            color = "transparent"

        try:
            self.configure(fg_color=color)
        except Exception as exc:
            logger.debug("apply_bg: %r", exc)

        self._apply_text_color()

    def _apply_text_color(self) -> None:
        """Цвет текста пункта: белый только на заливке."""
        if not self._danger:
            return

        color = (
            self._hover_text_color if self._hover
            else self._idle_text_color
        )
        labels = [self._text_label, self._icon_label]
        for label in labels:
            if label is None:
                continue
            try:
                label.configure(text_color=color)
            except Exception as exc:
                logger.debug("apply_text_color: %r", exc)


class ContextMenu:
    """Одноразовое контекстное меню."""

    def __init__(self, parent):
        self._parent = parent
        self._root = parent.winfo_toplevel()
        self._top: tk.Toplevel | None = None
        self._items: list[
            tuple[str, str | None, Callable[[], None] | None, bool]
        ] = []

        self._click_bind_id: str | None = None
        self._focus_bind_id: str | None = None

        # Button-3: отложенный bind (см. _bind_close).
        self._rclick_bind_id: str | None = None
        self._rclick_bind: str | None = None

    # --- Сборка ---

    def add_item(
        self,
        label: str,
        command: Callable[[], None],
        *,
        icon: str | None = None,
        danger: bool = False,
    ) -> ContextMenu:
        self._items.append((label, icon, command, danger))
        return self

    def add_separator(self) -> ContextMenu:
        self._items.append(("", None, None, False))
        return self

    # --- Показ ---

    def show(self, x_root: int, y_root: int) -> None:
        if not self._items:
            logger.debug("ContextMenu.show: пустое меню")
            return

        self.close()

        top = tk.Toplevel(self._parent)
        top.overrideredirect(True)
        try:
            top.attributes("-topmost", True)
        except Exception as exc:
            logger.debug("attributes(-topmost): %r", exc)
        _make_transparent(top)
        self._top = top

        outer = ctk.CTkFrame(
            top,
            fg_color=SURFACE_BG,
            corner_radius=SURFACE_RADIUS,
            border_width=_FRAME_BORDER_WIDTH,
            border_color=SURFACE_BORDER,
        )
        outer.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(outer, fg_color="transparent")
        inner.pack(
            fill="x",
            padx=_FRAME_PAD, pady=_FRAME_PAD,
        )

        last_action_idx: int | None = None
        for idx, (_, _, command, _) in enumerate(self._items):
            if command is not None:
                last_action_idx = idx

        for idx, (label, icon, command, danger) in enumerate(self._items):
            if command is None:
                sep = make_separator(inner)
                sep.pack(
                    fill="x",
                    padx=_SEPARATOR_PADX,
                    pady=_SEPARATOR_PADY,
                )
                continue

            is_last_action = (idx == last_action_idx)
            pady_bottom = 0 if is_last_action else _ITEM_PADY

            row = _MenuRow(
                inner,
                icon=icon or "",
                text=label,
                command=lambda cb=command: self._invoke(cb),
                danger=danger,
            )
            row.pack(fill="x", pady=(0, pady_bottom))

        top.update_idletasks()
        outer.update_idletasks()

        width = max(_MIN_WIDTH, outer.winfo_reqwidth())
        height = outer.winfo_reqheight()

        scaling = _get_scaling(self._parent)
        cursor_offset = round(_CURSOR_OFFSET * scaling)
        screen_margin = round(_SCREEN_MARGIN * scaling)

        px, py = self._clamp_to_screen(
            x_root + cursor_offset,
            y_root + cursor_offset,
            width, height,
            screen_margin,
        )
        top.geometry(f"{width}x{height}+{px}+{py}")

        self._bind_close()
        top.bind("<Escape>", lambda _e: self.close())

    # --- Закрытие ---

    def close(self) -> None:
        if self._top is None:
            return
        top = self._top
        self._top = None

        self._unbind_close()
        try:
            top.destroy()
        except Exception as exc:
            logger.debug("destroy контекстного меню: %r", exc)

    # --- Внутреннее ---

    def _invoke(self, callback: Callable[[], None]) -> None:
        self.close()
        try:
            callback()
        except Exception as exc:
            logger.error(
                "Ошибка пункта контекстного меню: %r", exc,
            )

    def _clamp_to_screen(
        self, x: int, y: int, w: int, h: int, margin: int,
    ) -> tuple[int, int]:
        try:
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()
        except Exception as exc:
            logger.debug("размер экрана: %r", exc)
            return x, y

        if x + w > sw - margin:
            x = max(margin, sw - w - margin)
        if y + h > sh - margin:
            y = max(margin, sh - h - margin)
        return x, y

    def _bind_close(self) -> None:
        try:
            self._click_bind_id = self._root.bind(
                "<Button-1>", self._on_global_click, add="+",
            )
        except Exception as exc:
            logger.debug("bind Button-1: %r", exc)
            self._click_bind_id = None

        # Button-3: сам правый клик, открывший меню, ещё
        # обрабатывается (bindtags: widget → class → toplevel).
        # Если забиндить Button-3 синхронно, он попадёт в
        # toplevel-обработчик того же события и закроет только
        # что созданное меню. after_idle гарантирует, что bind
        # вступит в силу уже после завершения текущего события.
        try:
            self._rclick_bind_id = self._root.after_idle(
                self._bind_rclick_close,
            )
        except Exception as exc:
            logger.debug("after_idle Button-3: %r", exc)
            self._rclick_bind_id = None

        try:
            self._focus_bind_id = self._root.bind(
                "<FocusOut>", self._on_focus_out, add="+",
            )
        except Exception as exc:
            logger.debug("bind FocusOut: %r", exc)
            self._focus_bind_id = None

    def _bind_rclick_close(self) -> None:
        """Отложенный bind Button-3 (см. _bind_close)."""
        self._rclick_bind_id = None
        if self._top is None:
            return
        try:
            self._rclick_bind = self._root.bind(
                "<Button-3>", self._on_global_click, add="+",
            )
        except Exception as exc:
            logger.debug("bind Button-3: %r", exc)
            self._rclick_bind = None

    def _unbind_close(self) -> None:
        if self._click_bind_id is not None:
            try:
                self._root.unbind(
                    "<Button-1>", self._click_bind_id,
                )
            except Exception as exc:
                logger.debug("unbind Button-1: %r", exc)
            self._click_bind_id = None

        if self._rclick_bind_id is not None:
            try:
                self._root.after_cancel(self._rclick_bind_id)
            except Exception as exc:
                logger.debug(
                    "after_cancel Button-3: %r", exc,
                )
            self._rclick_bind_id = None

        if self._rclick_bind is not None:
            try:
                self._root.unbind(
                    "<Button-3>", self._rclick_bind,
                )
            except Exception as exc:
                logger.debug("unbind Button-3: %r", exc)
            self._rclick_bind = None

        if self._focus_bind_id is not None:
            try:
                self._root.unbind(
                    "<FocusOut>", self._focus_bind_id,
                )
            except Exception as exc:
                logger.debug("unbind FocusOut: %r", exc)
            self._focus_bind_id = None

    def _on_global_click(self, event) -> None:
        if self._top is None:
            return
        if self._is_inside(event.x_root, event.y_root):
            return
        self.close()

    def _on_focus_out(self, _event=None) -> None:
        if self._top is None:
            return
        try:
            self._root.after(
                _FOCUS_CHECK_DELAY_MS, self._check_focus_lost,
            )
        except Exception as exc:
            logger.debug("after() при FocusOut: %r", exc)

    def _check_focus_lost(self) -> None:
        if self._top is None:
            return
        try:
            focused = self._root.focus_get()
        except Exception as exc:
            logger.debug("focus_get: %r", exc)
            return
        if focused is None:
            logger.debug(
                "фокус потерян — контекстное меню закрыто",
            )
            self.close()

    def _is_inside(self, x_root: int, y_root: int) -> bool:
        if self._top is None:
            return False
        try:
            x = self._top.winfo_rootx()
            y = self._top.winfo_rooty()
            w = self._top.winfo_width()
            h = self._top.winfo_height()
        except Exception as exc:
            logger.debug(
                "геометрия контекстного меню: %r", exc,
            )
            return False
        return x <= x_root <= x + w and y <= y_root <= y + h
