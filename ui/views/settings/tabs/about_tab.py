"""Вкладка «Описание»: название, версия и ссылка на README.

Ссылка открывает README.md программой, связанной с `.md`. Если
ассоциации нет — файл показывается во встроенном окне, чтобы
описание было доступно в любом случае.
"""

from __future__ import annotations

import customtkinter as ctk

from config.constants import APP_NAME, APP_VERSION
from core.paths import get_doc_path
from services.system.file_opener import try_open_associated
from ui.dialogs import show_error
from ui.dialogs.readme_view import show_readme
from ui.fonts import get_font
from ui.palette import ACCENT
from ui.views.settings.tabs.base_tab import SettingsTab
from utils.logger import get_logger

logger = get_logger(__name__)

_NAME_FONT_SIZE = 18
_LINK_FONT_SIZE = 13

_SECTION_PADY_TOP = 8

_README_NAME = "README.md"

_LINK_COLOR = ACCENT
_LINK_HOVER_COLOR = ("#6a8aae", "#3f5d82")


class AboutTab(SettingsTab):
    """Информация о приложении и ссылка на README."""

    def __init__(self, master, window, **kwargs):
        super().__init__(master, window, **kwargs)
        self._build()

    def _build(self) -> None:
        row = 0

        ctk.CTkLabel(
            self,
            text=APP_NAME,
            anchor="w",
            font=get_font(_NAME_FONT_SIZE, "bold"),
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=(_SECTION_PADY_TOP, 2),
        )
        row += 1

        ctk.CTkLabel(
            self,
            text=f"Версия {APP_VERSION}",
            anchor="w",
            text_color=("gray40", "gray60"),
            font=get_font(_LINK_FONT_SIZE),
        ).grid(
            row=row, column=0, sticky="w",
            padx=4, pady=(0, 6),
        )
        row += 1

        self._link = _LinkLabel(
            self,
            text=_README_NAME,
            command=self._open_readme,
        )
        self._link.grid(
            row=row, column=0, sticky="w",
            padx=4, pady=(0, 4),
        )
        row += 1

        # Предупреждение о пропавшем файле. В обычном состоянии
        # скрыто — при успехе ссылки пояснять нечего.
        self._hint = ctk.CTkLabel(
            self,
            text="",
            anchor="w",
            justify="left",
            text_color=("gray40", "gray60"),
            font=get_font(11),
        )
        self._hint.grid(
            row=row, column=0, sticky="w",
            padx=4, pady=(0, 8),
        )
        self._hint.grid_remove()

        self._sync_availability()

    # --- Состояние ---

    def _sync_availability(self) -> None:
        """Гасит ссылку, если README рядом с программой не найден."""
        if get_doc_path(_README_NAME) is None:
            self._link.set_enabled(False)
            self._hint.configure(
                text=(
                    "Файл README.md не найден рядом с программой. "
                    "Положите его в папку приложения."
                ),
            )
            self._hint.grid()
        else:
            self._link.set_enabled(True)
            self._hint.grid_remove()

    # --- Действие ---

    def _open_readme(self) -> None:
        path = get_doc_path(_README_NAME)
        if path is None:
            show_error(
                self.window,
                "Описание недоступно",
                "Файл README.md не найден рядом с программой.\n\n"
                "Положите README.md в папку с CCRun.exe и "
                "попробуйте снова.",
            )
            return

        target = str(path)
        result = try_open_associated(target)
        if result.success:
            logger.info("README открыт ассоциированной программой")
            return

        logger.info(
            "Ассоциации для .md нет (%s) — открываю встроенный просмотр",
            result.error,
        )
        show_readme(
            self.window,
            target,
            parent_visible=self.window.winfo_toplevel().state()
            in ("normal", "zoomed"),
        )


class _LinkLabel(ctk.CTkLabel):
    """Подпись, оформленная как ссылка: цвет, подчёркивание, курсор."""

    def __init__(self, master, *, text: str, command, **kwargs):
        super().__init__(
            master,
            text=text,
            anchor="w",
            text_color=_LINK_COLOR,
            font=get_font(_LINK_FONT_SIZE, "bold"),
            cursor="hand2",
            **kwargs,
        )
        self._command = command
        self._enabled = True
        self._plain = ctk.CTkFont(
            size=_LINK_FONT_SIZE, weight="bold",
        )
        self._underline = ctk.CTkFont(
            size=_LINK_FONT_SIZE, weight="bold", underline=True,
        )
        self.configure(font=self._plain)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda _e: self._on_hover(True))
        self.bind("<Leave>", lambda _e: self._on_hover(False))

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        try:
            self.configure(
                text_color=_LINK_COLOR if enabled else ("gray50", "gray50"),
                cursor="hand2" if enabled else "",
            )
        except Exception as exc:
            logger.debug("set_enabled ссылки: %r", exc)

    def _on_click(self, _event=None) -> None:
        if not self._enabled:
            return
        try:
            self._command()
        except Exception as exc:
            logger.exception("Ошибка открытия README: %r", exc)

    def _on_hover(self, hover: bool) -> None:
        if not self._enabled:
            return
        try:
            self.configure(
                text_color=(
                    _LINK_HOVER_COLOR if hover else _LINK_COLOR
                ),
                font=self._underline if hover else self._plain,
            )
        except Exception as exc:
            logger.debug("hover ссылки: %r", exc)
