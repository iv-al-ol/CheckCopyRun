"""Главный экран: инструкция и плитки быстрого доступа."""

from __future__ import annotations

import customtkinter as ctk

from core.models import Profile
from core.settings_store import save_settings
from ui.components.profile_tile import ProfileTile
from ui.components.scrollable import AutoHideScrollableFrame
from ui.components.separator import make_separator
from ui.fonts import get_font
from ui.views.base_view import BaseView
from utils.logger import get_logger

logger = get_logger(__name__)

_TITLE_FONT_SIZE = 22
_SECTION_FONT_SIZE = 15
_BODY_FONT_SIZE = 13

_PAGE_PADX = 24
_PAGE_PADY_TOP = 20
_SEPARATOR_PADY = 8
_BOTTOM_PADY = 20

_TILE_COLUMNS = 2
_TILE_GAP_X = 4
_TILE_GAP_Y = 4
_TILE_PADX = 4
_MAX_TILES = 10

_INTRO_TITLE = "Начало работы"

_INSTRUCTION_LINES = [
    "1.  Нажмите «Добавить профиль» для начала работы.",
    "2.  Выберите, что копировать, куда копировать "
    "и что запустить после копирования.",
    "3.  Установите необходимые опции для профиля.",
    "4.  Нажмите «Запустить» на плитке профиля "
    "или на кнопке ▶ в боковом меню.",
]


class MainView(BaseView):
    """Экран «Главный»."""

    def __init__(self, master, window):
        super().__init__(master, window)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._tiles: list[ProfileTile] = []
        self._busy = False

        self._build_instructions()
        self._build_separator()
        self._build_profiles_section()

    def on_show(self) -> None:
        self._rebuild_tiles()

    # --- Инструкция ---

    def _build_instructions(self) -> None:
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(
            row=0, column=0, sticky="ew",
            padx=_PAGE_PADX, pady=(_PAGE_PADY_TOP, 12),
        )
        box.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            box,
            text=_INTRO_TITLE,
            anchor="w",
            font=get_font(_TITLE_FONT_SIZE, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        ctk.CTkLabel(
            box,
            text="\n".join(_INSTRUCTION_LINES),
            anchor="w",
            justify="left",
            font=get_font(_BODY_FONT_SIZE),
            text_color=("gray30", "gray80"),
        ).grid(row=1, column=0, sticky="w")

    # --- Разделитель ---

    def _build_separator(self) -> None:
        sep = make_separator(self)
        sep.grid(
            row=1, column=0, sticky="ew",
            padx=_PAGE_PADX, pady=_SEPARATOR_PADY,
        )

    # --- Раздел с профилями ---

    def _build_profiles_section(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(
            row=2, column=0, sticky="nsew",
            padx=_PAGE_PADX, pady=(4, _BOTTOM_PADY),
        )
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            container,
            text="Профили",
            anchor="w",
            font=get_font(_SECTION_FONT_SIZE, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self._scroll = AutoHideScrollableFrame(
            container,
            fg_color="transparent",
            corner_radius=0,
        )
        self._scroll.grid(row=1, column=0, sticky="nsew")

        self._scroll.grid_columnconfigure(0, weight=1, uniform="tiles")
        self._scroll.grid_columnconfigure(1, weight=1, uniform="tiles")

        self._empty_label = ctk.CTkLabel(
            self._scroll,
            text=(
                "Пока ни одного профиля. Создайте первый через "
                "«Добавить профиль»."
            ),
            anchor="w",
            justify="left",
            text_color=("gray40", "gray60"),
            font=get_font(_BODY_FONT_SIZE),
        )

    def _rebuild_tiles(self) -> None:
        for tile in self._tiles:
            tile.destroy()
        self._tiles.clear()

        profiles = self._sorted_profiles()

        if not profiles:
            self._empty_label.grid(
                row=0, column=0, columnspan=_TILE_COLUMNS,
                sticky="w",
                padx=_TILE_PADX, pady=(4, 8),
            )
            self._after_layout()
            return

        self._empty_label.grid_forget()

        for idx, profile in enumerate(profiles):
            row = idx // _TILE_COLUMNS
            col = idx % _TILE_COLUMNS

            tile = ProfileTile(
                self._scroll,
                profile,
                on_open=self._on_open_profile,
                on_run=self._on_run,
                on_toggle_pin=self._on_toggle_pin,
            )
            tile.grid(
                row=row, column=col, sticky="nsew",
                padx=(
                    (0, _TILE_GAP_X // 2) if col == 0
                    else (_TILE_GAP_X // 2, 0)
                ),
                pady=(_TILE_GAP_Y // 2, _TILE_GAP_Y // 2),
            )
            self._tiles.append(tile)

        self._after_layout()

    def _after_layout(self) -> None:
        try:
            self._scroll.check_scroll()
            self.after(60, self._check_scroll_now)
            self.after(250, self._check_scroll_now)
        except Exception as exc:
            logger.debug("после раскладки: %r", exc)

    def _check_scroll_now(self) -> None:
        try:
            self._scroll.check_scroll_now()
        except Exception as exc:
            logger.debug("check_scroll_now: %r", exc)

    # --- Сортировка ---

    def _sorted_profiles(self) -> list[Profile]:
        profiles = list(self.window.settings.profiles)

        pinned = [p for p in profiles if p.pinned]
        used = [
            p for p in profiles
            if not p.pinned and p.last_used_at
        ]
        rest = [
            p for p in profiles
            if not p.pinned and not p.last_used_at
        ]

        pinned.sort(key=lambda p: p.last_used_at, reverse=True)
        used.sort(key=lambda p: p.last_used_at, reverse=True)
        rest.sort(key=lambda p: p.name_base)

        return (pinned + used + rest)[:_MAX_TILES]

    # --- Обработчики плиток ---

    def _find(self, pid: str) -> Profile | None:
        for p in self.window.settings.profiles:
            if p.id == pid:
                return p
        return None

    def _on_open_profile(self, pid: str) -> None:
        self.window.open_profile(pid)

    def _on_toggle_pin(self, pid: str) -> None:
        profile = self._find(pid)
        if profile is None:
            return

        profile.pinned = not profile.pinned
        save_settings(self.window.settings)
        self._rebuild_tiles()

        state = (
            "добавлен в избранное" if profile.pinned
            else "удалён из избранного"
        )
        self.window.set_status(
            f"Профиль {state}: {profile.display_name}",
        )

    def _on_run(self, pid: str) -> None:
        self.window.run_with_check(pid)
