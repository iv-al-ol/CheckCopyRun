"""Боковое меню с динамическим списком профилей."""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from config.constants import (
    DEFAULT_PROFILE_ICON,
    SEPARATOR_PADY,
    SIDEBAR_ITEM_HEIGHT,
    SIDEBAR_ITEM_PADY_TOP,
    SIDEBAR_SETTINGS_PADY_BOTTOM,
    SIDEBAR_WIDTH,
)
from core.models import Profile
from ui.components.image_utils import (
    load_ctk_image,
    looks_like_image_path,
)
from ui.components.scrollable import AutoHideScrollableFrame
from ui.components.separator import make_separator
from ui.components.tooltip import Tooltip
from ui.fonts import get_emoji_font, get_font
from ui.palette import SUCCESS, SUCCESS_HOVER, SUCCESS_TEXT
from utils.logger import get_logger

logger = get_logger(__name__)

# --- Ключи навигации ---
KEY_MAIN = "main"
KEY_SETTINGS = "settings"
PROFILE_KEY_PREFIX = "profile:"


def profile_key(profile_id: str) -> str:
    return f"{PROFILE_KEY_PREFIX}{profile_id}"


def parse_profile_key(key: str) -> str | None:
    if not key.startswith(PROFILE_KEY_PREFIX):
        return None
    return key[len(PROFILE_KEY_PREFIX):]


# --- Цвета ---
_NAV_BG = ("gray90", "gray17")
_HOVER_COLOR = ("gray80", "gray25")
_ACTIVE_COLOR = ("gray70", "gray30")
_TEXT_COLOR = ("gray10", "gray90")

# --- Геометрия ---
_ITEM_RADIUS = 8
_ITEM_PADX = 8
_RUN_BUTTON_WIDTH = 28
_RUN_BUTTON_PADX = 6
_FONT_SIZE = 13
_EMOJI_FONT_SIZE = 14

_ICON_WRAPPER_SIZE = 28
_ICON_WRAPPER_PADX_LEFT = 8
_ICON_WRAPPER_PADX_RIGHT = 4

_SEPARATOR_PADX = 12

_RUN_TOOLTIP_TEXT = "Проверить директорию и запустить приложение"
_RUN_TOOLTIP_DELAY_MS = 400


class _NavItem(ctk.CTkFrame):
    """Пункт сайдбара: иконка + текст + опциональная кнопка запуска."""

    def __init__(
        self,
        master,
        *,
        icon: str,
        text: str,
        on_click: Callable[[], None],
        on_context: Callable[[int, int], None] | None = None,
        on_run: Callable[[], None] | None = None,
        run_tooltip: str | None = None,
        bold: bool = False,
    ):
        super().__init__(
            master,
            fg_color=_NAV_BG,
            corner_radius=_ITEM_RADIUS,
            height=SIDEBAR_ITEM_HEIGHT,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._on_click_cb = on_click
        self._active = False
        self._hover = False
        self._run_tooltip: Tooltip | None = None

        icon_wrapper = ctk.CTkFrame(
            self,
            fg_color="transparent",
            width=_ICON_WRAPPER_SIZE,
            height=_ICON_WRAPPER_SIZE,
        )
        icon_wrapper.grid_propagate(False)
        icon_wrapper.grid(
            row=0, column=0,
            padx=(_ICON_WRAPPER_PADX_LEFT, _ICON_WRAPPER_PADX_RIGHT),
        )

        image = (
            load_ctk_image(icon, _ICON_WRAPPER_SIZE)
            if looks_like_image_path(icon)
            else None
        )
        if image is not None:
            icon_label: ctk.CTkLabel = ctk.CTkLabel(
                icon_wrapper, image=image, text="",
            )
        else:
            icon_label = ctk.CTkLabel(
                icon_wrapper,
                text=icon or " ",
                anchor="center",
                font=get_emoji_font(_EMOJI_FONT_SIZE),
                text_color=_TEXT_COLOR,
            )
        icon_label.place(relx=0.5, rely=0.5, anchor="center")

        self._text_label = ctk.CTkLabel(
            self,
            text=text,
            anchor="w",
            justify="left",
            text_color=_TEXT_COLOR,
            font=get_font(_FONT_SIZE, "bold" if bold else "normal"),
        )
        self._text_label.grid(
            row=0, column=1, sticky="ew", padx=(0, 8),
        )

        self._run_button: ctk.CTkButton | None = None
        if on_run is not None:
            self._run_button = ctk.CTkButton(
                self,
                text="▶",
                width=_RUN_BUTTON_WIDTH,
                height=SIDEBAR_ITEM_HEIGHT - 10,
                corner_radius=6,
                font=get_font(11),
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

        targets: list = [self, icon_wrapper, icon_label, self._text_label]
        for w in targets:
            w.bind("<Button-1>", self._handle_click, add="+")
            w.bind("<Enter>", self._handle_enter, add="+")
            w.bind("<Leave>", self._handle_leave, add="+")
            if on_context is not None:
                w.bind(
                    "<Button-3>",
                    lambda e, cb=on_context: cb(e.x_root, e.y_root),
                    add="+",
                )

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_bg()

    def _handle_click(self, _event=None) -> None:
        try:
            self._on_click_cb()
        except Exception as exc:
            logger.error("Ошибка клика пункта: %r", exc)

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
        if self._active:
            color = _ACTIVE_COLOR
        elif self._hover:
            color = _HOVER_COLOR
        else:
            color = _NAV_BG
        try:
            self.configure(fg_color=color)
        except Exception as exc:
            logger.debug("configure(fg_color): %r", exc)


class Sidebar(ctk.CTkFrame):
    """Сайдбар: фиксированные пункты + динамический список профилей."""

    def __init__(
        self,
        master,
        *,
        on_select: Callable[[str], None],
        on_add_profile: Callable[[], None],
        on_run_profile: Callable[[str], None],
        on_profile_context: Callable[[str, int, int], None],
        title: str = "CheckCopyRun",
        width: int = SIDEBAR_WIDTH,
    ):
        super().__init__(
            master, width=width, corner_radius=0, fg_color=_NAV_BG,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._on_select = on_select
        self._on_add_profile = on_add_profile
        self._on_run_profile = on_run_profile
        self._on_profile_context = on_profile_context

        self._nav_items: dict[str, _NavItem] = {}
        self._profile_rows: dict[str, _NavItem] = {}
        self._active_key: str | None = None

        self._build_static(title)
        self._profiles_container = self._build_scroll_and_bottom()

    def _build_static(self, title: str) -> None:
        ctk.CTkLabel(
            self, text=title, font=get_font(17, "bold"),
            text_color=_TEXT_COLOR,
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(20, 16))

        self._add_nav_item(
            row=1, key=KEY_MAIN, icon="🏠", text="Главный", bold=True,
        )
        self._add_separator(row=2)

        add_item = _NavItem(
            self,
            icon="➕",
            text="Добавить профиль",
            on_click=self._safe_call_noarg(
                self._on_add_profile, "add profile",
            ),
            bold=True,
        )
        add_item.grid(
            row=3, column=0, sticky="ew",
            padx=_ITEM_PADX,
            pady=(SIDEBAR_ITEM_PADY_TOP, SIDEBAR_ITEM_PADY_TOP),
        )
        self._nav_items["add"] = add_item

    def _build_scroll_and_bottom(self) -> AutoHideScrollableFrame:
        scroll = AutoHideScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
        )
        scroll.grid(row=4, column=0, sticky="nsew", pady=(4, 4))
        scroll.grid_columnconfigure(0, weight=1)

        self._add_separator(row=5)
        self._add_nav_item(
            row=6, key=KEY_SETTINGS,
            icon="⚙️", text="Настройки",
            bold=True, pady_bottom=SIDEBAR_SETTINGS_PADY_BOTTOM,
        )
        return scroll

    def _add_separator(self, row: int) -> None:
        sep = make_separator(self)
        sep.grid(
            row=row, column=0, sticky="ew",
            padx=_SEPARATOR_PADX, pady=SEPARATOR_PADY,
        )

    def _add_nav_item(
        self,
        *,
        row: int,
        key: str,
        icon: str,
        text: str,
        bold: bool = False,
        pady_bottom: int = SIDEBAR_ITEM_PADY_TOP,
    ) -> _NavItem:
        item = _NavItem(
            self,
            icon=icon,
            text=text,
            on_click=self._safe_call_noarg(
                lambda k=key: self._on_select(k), f"select {key}",
            ),
            bold=bold,
        )
        item.grid(
            row=row, column=0, sticky="ew",
            padx=_ITEM_PADX,
            pady=(SIDEBAR_ITEM_PADY_TOP, pady_bottom),
        )
        self._nav_items[key] = item
        return item

    def rebuild_profiles(self, profiles: list[Profile]) -> None:
        for row in self._profile_rows.values():
            row.destroy()
        self._profile_rows.clear()

        for idx, p in enumerate(profiles):
            row = self._make_profile_row(p)
            row.grid(
                row=idx, column=0, sticky="ew",
                padx=_ITEM_PADX, pady=2,
            )
            self._profile_rows[p.id] = row

        if self._active_key is not None:
            self.set_active(self._active_key)

        try:
            self._profiles_container.check_scroll()
        except Exception as exc:
            logger.debug("check_scroll: %r", exc)

    def set_active(self, key: str) -> None:
        self._active_key = key
        for nav_key, item in self._nav_items.items():
            item.set_active(nav_key == key)
        for pid, item in self._profile_rows.items():
            item.set_active(profile_key(pid) == key)

    def _make_profile_row(self, profile: Profile) -> _NavItem:
        # Кнопка запуска доступна, если можно копировать: сам клик
        # выполнит копирование и затем запуск.
        on_run = None
        if profile.can_copy():
            on_run = self._safe_call_noarg(
                lambda pid=profile.id: self._on_run_profile(pid),
                f"run profile {profile.id}",
            )

        def on_context(x: int, y: int, pid: str = profile.id) -> None:
            try:
                self._on_profile_context(pid, x, y)
            except Exception as exc:
                logger.error(
                    "Ошибка контекстного меню профиля %s: %r",
                    pid, exc,
                )

        return _NavItem(
            self._profiles_container,
            icon=profile.icon or DEFAULT_PROFILE_ICON,
            text=profile.display_name,
            on_click=self._safe_call_noarg(
                lambda pid=profile.id: self._on_select(
                    profile_key(pid),
                ),
                f"select profile {profile.id}",
            ),
            on_context=on_context,
            on_run=on_run,
            run_tooltip=_RUN_TOOLTIP_TEXT if on_run else None,
        )

    @staticmethod
    def _safe_call_noarg(callback: Callable[[], None], what: str):
        def wrapper() -> None:
            try:
                callback()
            except Exception as exc:
                logger.error("Ошибка %s: %r", what, exc)
        return wrapper
