"""Плитка профиля для главного экрана.

Действия: Запустить и Закрепить/Открепить.
  • Запустить доступно, если заданы source и destination.
  • Закрепить: ★ (BLACK STAR, U+2605) — закреплён, золотая;
              ☆ (WHITE STAR, U+2606) — откреплён, обычный цвет.

Используются классические текстовые символы звёзд, а не emoji ⭐
(U+2B50): emoji может рендериться как пустая звезда в fallback-шрифте.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import customtkinter as ctk

from config.constants import DEFAULT_PROFILE_ICON
from core.models import Profile
from ui.components.image_utils import (
    load_ctk_image,
    looks_like_image_path,
)
from ui.components.tooltip import Tooltip
from ui.fonts import get_emoji_font, get_font
from ui.palette import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_TEXT,
    SUCCESS,
    SUCCESS_HOVER,
    SUCCESS_TEXT,
    SURFACE_BG,
    SURFACE_BORDER,
    SURFACE_HOVER,
    SURFACE_RADIUS,
    SURFACE_TEXT,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_TILE_PADX = 12
_TILE_PADY_TOP_BOTTOM = 10
_TILE_RADIUS = SURFACE_RADIUS

_ICON_SIZE = 40
_ICON_FONT_SIZE = 24
_ICON_PADX_RIGHT = 12

_NAME_FONT_SIZE = 13
_PATH_FONT_SIZE = 11

_BUTTON_SIZE = 30
_BUTTON_PADX = 4
_BUTTON_RADIUS = 6
_BUTTON_FONT_SIZE = 14

_TOOLTIP_RUN = "Запустить"
_TOOLTIP_PINNED = "Добавлено в избранное"
_TOOLTIP_UNPINNED = "Добавить в избранное"
_TOOLTIP_DELAY_MS = 400

_ICON_RUN = "▶"

# Звёзды: классические текстовые символы (не emoji).
# ★ U+2605 BLACK STAR — заполненная, ☆ U+2606 WHITE STAR — контурная.
_ICON_PIN_ON = "★"
_ICON_PIN_OFF = "☆"

# Цвета текста звёзд: золотой для закреплённой, обычный для откреплённой.
_PIN_ON_TEXT_COLOR = ("#b8860b", "#ffd700")   # darkgoldenrod / gold
_PIN_OFF_TEXT_COLOR = ACCENT_TEXT              # белый на синем фоне


class ProfileTile(ctk.CTkFrame):
    """Плитка профиля с двумя действиями."""

    def __init__(
        self,
        master,
        profile: Profile,
        *,
        on_open: Callable[[str], None],
        on_run: Callable[[str], None],
        on_toggle_pin: Callable[[str], None],
    ):
        super().__init__(
            master,
            fg_color=SURFACE_BG,
            corner_radius=_TILE_RADIUS,
            border_width=1,
            border_color=SURFACE_BORDER,
        )
        self.grid_columnconfigure(1, weight=1)

        self._profile = profile
        self._on_open = on_open
        self._on_run = on_run
        self._on_toggle_pin = on_toggle_pin

        self._hover = False
        self._tooltips: list[Tooltip] = []
        self._clickable_widgets: list = []

        self._build_icon()
        self._build_texts()
        self._build_actions()
        self._bind_hover()

    def _build_icon(self) -> None:
        wrapper = ctk.CTkFrame(
            self,
            fg_color="transparent",
            width=_ICON_SIZE,
            height=_ICON_SIZE,
        )
        wrapper.grid_propagate(False)
        wrapper.grid(
            row=0, column=0,
            padx=(_TILE_PADX, _ICON_PADX_RIGHT),
            pady=_TILE_PADY_TOP_BOTTOM,
        )

        image = (
            load_ctk_image(self._profile.icon, _ICON_SIZE)
            if looks_like_image_path(self._profile.icon)
            else None
        )
        if image is not None:
            label = ctk.CTkLabel(wrapper, image=image, text="")
        else:
            label = ctk.CTkLabel(
                wrapper,
                text=self._profile.icon or DEFAULT_PROFILE_ICON,
                anchor="center",
                font=get_emoji_font(_ICON_FONT_SIZE),
                text_color=SURFACE_TEXT,
            )
        label.place(relx=0.5, rely=0.5, anchor="center")

        self._clickable_widgets = [wrapper, label]

    def _build_texts(self) -> None:
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(
            row=0, column=1, sticky="ew",
            pady=_TILE_PADY_TOP_BOTTOM,
        )
        box.grid_columnconfigure(0, weight=1)

        name = ctk.CTkLabel(
            box,
            text=self._profile.display_name,
            anchor="w",
            justify="left",
            text_color=SURFACE_TEXT,
            font=get_font(_NAME_FONT_SIZE, "bold"),
        )
        name.grid(row=0, column=0, sticky="ew")

        short = self._short_paths(self._profile)
        path_label = ctk.CTkLabel(
            box,
            text=short,
            anchor="w",
            justify="left",
            text_color=("gray40", "gray60"),
            font=get_font(_PATH_FONT_SIZE),
        )
        path_label.grid(row=1, column=0, sticky="ew")

        full = self._full_paths(self._profile)
        if full:
            self._tooltips.append(
                Tooltip(path_label, full, delay_ms=_TOOLTIP_DELAY_MS),
            )

        self._clickable_widgets.extend([box, name, path_label])

    def _build_actions(self) -> None:
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(
            row=0, column=2,
            padx=(8, _TILE_PADX),
            pady=_TILE_PADY_TOP_BOTTOM,
        )

        # Запустить — зелёная.
        self._run_btn = self._icon_button(
            actions,
            icon=_ICON_RUN,
            tooltip=_TOOLTIP_RUN,
            command=lambda: self._on_run(self._profile.id),
            enabled=self._profile.can_copy(),
            fg_color=SUCCESS,
            hover_color=SUCCESS_HOVER,
            text_color=SUCCESS_TEXT,
        )
        self._run_btn.pack(side="left", padx=(0, _BUTTON_PADX))

        # Закрепить/Открепить — синяя.
        # ★ золотая (закреплён) / ☆ белая (откреплён).
        pinned = self._profile.pinned
        pin_icon = _ICON_PIN_ON if pinned else _ICON_PIN_OFF
        pin_tooltip = (
            _TOOLTIP_PINNED if pinned else _TOOLTIP_UNPINNED
        )
        pin_text_color = (
            _PIN_ON_TEXT_COLOR if pinned else _PIN_OFF_TEXT_COLOR
        )
        self._pin_btn = self._icon_button(
            actions,
            icon=pin_icon,
            tooltip=pin_tooltip,
            command=lambda: self._on_toggle_pin(self._profile.id),
            enabled=True,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=pin_text_color,
        )
        self._pin_btn.pack(side="left")

    def _icon_button(
        self,
        master,
        *,
        icon: str,
        tooltip: str,
        command: Callable[[], None],
        enabled: bool,
        fg_color=None,
        hover_color=None,
        text_color=None,
    ) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            master,
            text=icon,
            width=_BUTTON_SIZE,
            height=_BUTTON_SIZE,
            corner_radius=_BUTTON_RADIUS,
            fg_color=fg_color if fg_color is not None else "transparent",
            hover_color=(
                hover_color if hover_color is not None
                else SURFACE_HOVER
            ),
            text_color=(
                text_color if text_color is not None
                else SURFACE_TEXT
            ),
            font=get_font(_BUTTON_FONT_SIZE),
            command=command,
        )
        if not enabled:
            btn.configure(state="disabled")
        else:
            self._tooltips.append(
                Tooltip(btn, tooltip, delay_ms=_TOOLTIP_DELAY_MS),
            )
        return btn

    def _bind_hover(self) -> None:
        for w in [self, *self._clickable_widgets]:
            w.bind("<Enter>", self._on_enter, add="+")
            w.bind("<Leave>", self._on_leave, add="+")
            w.bind("<Button-1>", self._on_body_click, add="+")

    def _on_enter(self, _event=None) -> None:
        if not self._hover:
            self._hover = True
            self._apply_bg(True)

    def _on_leave(self, _event=None) -> None:
        try:
            self.after(20, self._check_hover)
        except Exception as exc:
            logger.debug("after() при Leave плитки: %r", exc)

    def _check_hover(self) -> None:
        try:
            under = self.winfo_containing(
                self.winfo_pointerx(), self.winfo_pointery(),
            )
        except Exception as exc:
            logger.debug("winfo_containing плитки: %r", exc)
            return
        if under is None or not self._is_inside(under):
            if self._hover:
                self._hover = False
                self._apply_bg(False)

    def _is_inside(self, widget) -> bool:
        current = widget
        while current is not None:
            if current is self:
                return True
            current = getattr(current, "master", None)
        return False

    def _apply_bg(self, hover: bool) -> None:
        try:
            self.configure(
                fg_color=SURFACE_HOVER if hover else SURFACE_BG,
            )
        except Exception as exc:
            logger.debug("hover плитки: %r", exc)

    def _on_body_click(self, _event=None) -> None:
        try:
            self._on_open(self._profile.id)
        except Exception as exc:
            logger.error(
                "Открытие профиля %s: %r", self._profile.id, exc,
            )

    @staticmethod
    def _short_paths(profile: Profile) -> str:
        src = profile.source
        dst = profile.destination
        if not src and not dst:
            return "Директории не заданы"
        src_short = os.path.basename(src.rstrip("/\\")) if src else "?"
        dst_short = os.path.basename(dst.rstrip("/\\")) if dst else "?"
        return f"{src_short}  →  {dst_short}"

    @staticmethod
    def _full_paths(profile: Profile) -> str:
        src = profile.source or "—"
        dst = profile.destination or "—"
        if profile.source or profile.destination:
            return f"{src}\n{dst}"
        return ""
