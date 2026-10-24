"""Боковое меню с динамическим списком профилей.

Публичный API:
    Sidebar(master, *, on_select, on_add_profile, on_run_profile,
            on_profile_context, ...)

    rebuild_profiles(profiles)   — пересобрать список профилей;
    set_active(key)              — отметить активный (открытый) пункт;
    clear_selection()            — сбросить множественное выделение;
    get_selected_ids()           — текущее выделение (list[str]).

Множественное выделение:
  • Ctrl+клик — toggle;
  • Shift+клик — диапазон от anchor;
  • ПКМ по невыделенному — выделяется один;
  • drag по пустому месту — рамка выделения. Выделение
    обновляется в реальном времени на каждом движении мыши.
  • клик ЛКМ или ПКМ вне списка профилей — сбрасывает
    выделение (контентная область, статус-бар, заголовок
    сайдбара, «Главный», «Настройки», «Добавить профиль»).
    ПКМ внутри списка — контекстное меню профиля, не сброс.

on_profile_context принимает (pids, x_root, y_root).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from config.constants import (
    DEFAULT_PROFILE_ICON,
    SEPARATOR_PADY,
    SIDEBAR_ITEM_PADY_TOP,
    SIDEBAR_SETTINGS_PADY_BOTTOM,
    SIDEBAR_WIDTH,
)
from core.models import Profile
from services.selection_model import SelectionModel
from ui.components.nav_item import (
    NAV_BG,
    NAV_TEXT,
    NavItem,
)
from ui.components.scrollable import AutoHideScrollableFrame
from ui.components.separator import make_separator
from ui.fonts import get_font
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


# --- Геометрия и тексты ---
_ITEM_PADX = 8
_SEPARATOR_PADX = 12

_ADD_PROFILE_LABEL = "Добавить профиль"
_RUN_TOOLTIP_TEXT = "Запустить"
_TITLE_FONT_SIZE = 17

# Модификаторы event.state.
_STATE_SHIFT = 0x0001
_STATE_CTRL = 0x0004

# Рамка выделения.
_DRAG_RECT_MIN_SIZE = 5
_DRAG_RECT_ALPHA = 0.35
_DRAG_RECT_COLOR = "#3a8bdc"


class Sidebar(ctk.CTkFrame):
    """Сайдбар: фиксированные пункты + динамический список профилей."""

    def __init__(
        self,
        master,
        *,
        on_select: Callable[[str], None],
        on_add_profile: Callable[[], None],
        on_run_profile: Callable[[str], None],
        on_profile_context: Callable[[list[str], int, int], None],
        title: str = "CheckCopyRun",
        width: int = SIDEBAR_WIDTH,
    ):
        super().__init__(
            master, width=width, corner_radius=0, fg_color=NAV_BG,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._on_select = on_select
        self._on_add_profile = on_add_profile
        self._on_run_profile = on_run_profile
        self._on_profile_context = on_profile_context

        self._nav_items: dict[str, NavItem] = {}
        self._profile_rows: dict[str, NavItem] = {}
        self._active_key: str | None = None

        self._selection = SelectionModel()

        # Состояние drag-выделения.
        self._drag_start: tuple[int, int] | None = None
        self._drag_rect: tk.Toplevel | None = None
        self._drag_active = False
        self._drag_item_rects: (
            dict[str, tuple[int, int, int, int]] | None
        ) = None

        self._build_static(title)
        self._profiles_container = self._build_scroll_and_bottom()
        self._setup_drag_selection()
        self._setup_global_click()

    # --- Статическая часть ---

    def _build_static(self, title: str) -> None:
        ctk.CTkLabel(
            self,
            text=title,
            font=get_font(_TITLE_FONT_SIZE, "bold"),
            text_color=NAV_TEXT,
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(20, 16))

        self._add_nav_item(
            row=1, key=KEY_MAIN, icon="🏠", text="Главный", bold=True,
        )
        self._add_separator(row=2)

        add_item = NavItem(
            self,
            icon="➕",
            text=_ADD_PROFILE_LABEL,
            on_click=self._wrap_click(
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
    ) -> NavItem:
        item = NavItem(
            self,
            icon=icon,
            text=text,
            on_click=self._wrap_click(
                lambda k=key: self._on_select(k),
                f"select {key}",
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

    # --- Профили ---

    def rebuild_profiles(self, profiles: list[Profile]) -> None:
        # Активный drag может содержать устаревшие rects —
        # отменяем его.
        self._reset_drag_state()

        for row in self._profile_rows.values():
            row.destroy()
        self._profile_rows.clear()

        self._selection.set_items([p.id for p in profiles])

        for idx, p in enumerate(profiles):
            row = self._make_profile_row(p)
            row.grid(
                row=idx, column=0, sticky="ew",
                padx=_ITEM_PADX, pady=2,
            )
            self._profile_rows[p.id] = row

        if self._active_key is not None:
            self.set_active(self._active_key)

        self._apply_selection()

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

    def clear_selection(self) -> None:
        self._selection.clear()
        self._apply_selection()

    def get_selected_ids(self) -> list[str]:
        return self._selection.get_selected()

    # --- Построение строки профиля ---

    def _make_profile_row(self, profile: Profile) -> NavItem:
        on_run = None
        if profile.can_copy():
            on_run = self._wrap_noarg(
                lambda pid=profile.id: self._on_run_profile(pid),
                f"run profile {profile.id}",
            )

        item = NavItem(
            self._profiles_container,
            icon=profile.icon or DEFAULT_PROFILE_ICON,
            text=profile.display_name,
            on_click=lambda ev, pid=profile.id: (
                self._handle_profile_click(pid, ev)
            ),
            on_run=on_run,
            run_tooltip=_RUN_TOOLTIP_TEXT if on_run else None,
        )
        item.set_on_context(
            lambda ev, pid=profile.id: (
                self._handle_profile_context(pid, ev)
            ),
        )
        return item

    # --- Обработчики профиля ---

    def _handle_profile_click(
        self, pid: str, event,
    ) -> None:
        ctrl = bool(event.state & _STATE_CTRL)
        shift = bool(event.state & _STATE_SHIFT)

        self._selection.handle_click(
            pid, ctrl=ctrl, shift=shift,
        )
        self._apply_selection()

        # Навигация — только без модификаторов.
        if not ctrl and not shift:
            try:
                self._on_select(profile_key(pid))
            except Exception as exc:
                logger.error(
                    "Ошибка навигации профиля %s: %r", pid, exc,
                )

    def _handle_profile_context(
        self, pid: str, event,
    ) -> None:
        self._selection.handle_right_click(pid)
        self._apply_selection()

        pids = self._selection.get_selected() or [pid]
        try:
            self._on_profile_context(
                pids, event.x_root, event.y_root,
            )
        except Exception as exc:
            logger.error(
                "Ошибка контекстного меню профиля: %r", exc,
            )

    def _apply_selection(self) -> None:
        selected = self._selection.get_selected_set()
        for pid, item in self._profile_rows.items():
            try:
                item.set_selected(pid in selected)
            except Exception as exc:
                logger.debug("set_selected: %r", exc)

    # --- Глобальный клик: сброс выделения вне списка ---

    def _setup_global_click(self) -> None:
        """Клик (ЛКМ или ПКМ) вне списка профилей — сброс.

        Bind на toplevel главного окна. Порядок bindtags:
        widget → class → toplevel → all. Клик по NavItem
        сначала обновляет selection в самом NavItem (для ЛКМ —
        через _handle_profile_click, для ПКМ — через
        _handle_profile_context), затем срабатывает наш
        toplevel-handler; он видит, что клик внутри
        _profiles_container, и не сбрасывает.

        Диалоги и контекстные меню — отдельные Toplevel,
        здесь их не касается.
        """
        try:
            root = self.winfo_toplevel()
            root.bind(
                "<Button-1>", self._on_global_click, add="+",
            )
            root.bind(
                "<Button-3>", self._on_global_click, add="+",
            )
        except Exception as exc:
            logger.debug(
                "bind global click: %r", exc,
            )

    def _on_global_click(self, event) -> None:
        if self._is_inside_profiles_container(event.widget):
            return
        # Клик вне списка профилей — сбрасываем множественное
        # выделение.
        if self._selection.count() == 0:
            return
        self.clear_selection()

    def _is_inside_profiles_container(self, widget) -> bool:
        """Клик внутри списка профилей (пункт, canvas, frame,
        скроллбар) — не сбрасываем: там своя логика.
        """
        current = widget
        while current is not None:
            if current is self._profiles_container:
                return True
            current = getattr(current, "master", None)
        return False

    # --- Drag-выделение ---

    def _setup_drag_selection(self) -> None:
        """Bind на внутренний canvas: только клики вне NavItem
        начинают рамку."""
        try:
            canvas = self._profiles_container._parent_canvas
        except Exception as exc:
            logger.debug("drag: canvas недоступен: %r", exc)
            return

        canvas.bind(
            "<ButtonPress-1>",
            self._on_drag_start, add="+",
        )
        canvas.bind(
            "<B1-Motion>",
            self._on_drag_motion, add="+",
        )
        canvas.bind(
            "<ButtonRelease-1>",
            self._on_drag_end, add="+",
        )

    def _is_inside_nav_item(self, widget) -> bool:
        current = widget
        while current is not None:
            if isinstance(current, NavItem):
                return True
            current = getattr(current, "master", None)
        return False

    def _on_drag_start(self, event) -> None:
        if self._is_inside_nav_item(event.widget):
            self._drag_start = None
            return
        self._reset_drag_state()
        self._drag_start = (event.x_root, event.y_root)

    def _on_drag_motion(self, event) -> None:
        if self._drag_start is None:
            return
        x0, y0 = self._drag_start
        x1, y1 = event.x_root, event.y_root

        if not self._drag_active:
            if (
                abs(x1 - x0) < _DRAG_RECT_MIN_SIZE
                and abs(y1 - y0) < _DRAG_RECT_MIN_SIZE
            ):
                return
            self._drag_active = True
            self._drag_item_rects = self._collect_item_rects()
            self._create_drag_rect()

        self._update_drag_rect(x0, y0, x1, y1)

        if self._drag_item_rects is not None:
            rect = (
                min(x0, x1), min(y0, y1),
                max(x0, x1), max(y0, y1),
            )
            ids = self._selection.ids_in_rect(
                rect, self._drag_item_rects,
            )
            self._selection.select_many(ids)
            self._apply_selection()

    def _on_drag_end(self, event) -> None:
        self._reset_drag_state()

    def _reset_drag_state(self) -> None:
        self._destroy_drag_rect()
        self._drag_start = None
        self._drag_active = False
        self._drag_item_rects = None

    def _create_drag_rect(self) -> None:
        try:
            rect = tk.Toplevel(self)
            rect.overrideredirect(True)
            try:
                rect.attributes("-topmost", True)
                rect.attributes("-alpha", _DRAG_RECT_ALPHA)
            except Exception as exc:
                logger.debug("drag: attributes: %r", exc)
            rect.configure(bg=_DRAG_RECT_COLOR)
            self._drag_rect = rect
        except Exception as exc:
            logger.error("drag: не создать рамку: %r", exc)
            self._drag_rect = None

    def _update_drag_rect(
        self, x0: int, y0: int, x1: int, y1: int,
    ) -> None:
        if self._drag_rect is None:
            return
        left = min(x0, x1)
        top = min(y0, y1)
        width = max(1, abs(x1 - x0))
        height = max(1, abs(y1 - y0))
        try:
            self._drag_rect.geometry(
                f"{width}x{height}+{left}+{top}"
            )
        except Exception as exc:
            logger.debug("drag: geometry: %r", exc)

    def _destroy_drag_rect(self) -> None:
        if self._drag_rect is None:
            return
        try:
            self._drag_rect.destroy()
        except Exception as exc:
            logger.debug("drag: destroy: %r", exc)
        self._drag_rect = None

    def _collect_item_rects(
        self,
    ) -> dict[str, tuple[int, int, int, int]]:
        result: dict[str, tuple[int, int, int, int]] = {}
        for pid, item in self._profile_rows.items():
            try:
                x = item.winfo_rootx()
                y = item.winfo_rooty()
                w = item.winfo_width()
                h = item.winfo_height()
                result[pid] = (x, y, x + w, y + h)
            except Exception:
                continue
        return result

    # --- Обёртки кликов ---

    @staticmethod
    def _wrap_click(callback: Callable[[], None], what: str):
        """Для статических пунктов: on_click(event) → callback()."""
        def wrapper(_event=None) -> None:
            try:
                callback()
            except Exception as exc:
                logger.error("Ошибка %s: %r", what, exc)
        return wrapper

    @staticmethod
    def _wrap_noarg(callback: Callable[[], None], what: str):
        """Для on_run: callback() без event."""
        def wrapper() -> None:
            try:
                callback()
            except Exception as exc:
                logger.error("Ошибка %s: %r", what, exc)
        return wrapper
