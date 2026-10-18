"""Экран настроек приложения."""

from __future__ import annotations

import subprocess

import customtkinter as ctk

from config.constants import (
    APP_NAME,
    APP_VERSION,
    SEPARATOR_PADY,
    THEME_DEFAULT,
)
from core.settings_store import get_settings_path
from ui.components.button import (
    VARIANT_DANGER,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.components.clipboard import enable_clipboard
from ui.components.option_menu import StyledOptionMenu
from ui.components.scrollable import AutoHideScrollableFrame
from ui.components.separator import make_separator
from ui.dialogs import ask_yes_no, show_error, show_info
from ui.fonts import get_font
from ui.themes import THEME_LABELS, apply_theme
from ui.views.base_view import BaseView
from utils.logger import get_logger

logger = get_logger(__name__)

_TITLE_FONT_SIZE = 22
_SECTION_FONT_SIZE = 15
_BODY_FONT_SIZE = 13
_HINT_FONT_SIZE = 11

_PAGE_PADX = 24
_PAGE_PADY_TOP = 20
_SECTION_PADY_TOP = 16

_ROW_BUTTON_WIDTH = 200
_OPTION_MENU_WIDTH = 220


class SettingsView(BaseView):
    """Экран настроек: внешний вид, поведение, данные, сброс."""

    def __init__(self, master, window):
        super().__init__(master, window)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()

    # --- Публичное ---

    def on_show(self) -> None:
        self._sync_from_settings()

    # --- Шапка ---

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(
            row=0, column=0, sticky="ew",
            padx=_PAGE_PADX, pady=(_PAGE_PADY_TOP, 12),
        )
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Настройки",
            anchor="w",
            font=get_font(_TITLE_FONT_SIZE, "bold"),
        ).grid(row=0, column=0, sticky="w")

    # --- Тело ---

    def _build_body(self) -> None:
        self._scroll = AutoHideScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
        )
        self._scroll.grid(
            row=1, column=0, sticky="nsew",
            padx=_PAGE_PADX, pady=(0, 20),
        )
        self._scroll.grid_columnconfigure(0, weight=1)

        self._build_appearance_section()
        self._build_behavior_section()
        self._build_data_section()
        self._build_reset_section()
        self._build_about_section()

    # --- Секция: Внешний вид ---

    def _build_appearance_section(self) -> None:
        section = self._make_section("Внешний вид")

        ctk.CTkLabel(
            section, text="Тема:", anchor="w",
            font=get_font(_BODY_FONT_SIZE),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=8)

        self._theme_var = ctk.StringVar(
            value=THEME_LABELS.get(THEME_DEFAULT, "Системная"),
        )
        StyledOptionMenu(
            section,
            values=list(THEME_LABELS.values()),
            variable=self._theme_var,
            command=self._on_theme_change,
            width=_OPTION_MENU_WIDTH,
        ).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=8)

    # --- Секция: Поведение ---

    def _build_behavior_section(self) -> None:
        section = self._make_section("Поведение")

        self._confirm_exit_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            section,
            text="Спрашивать подтверждение при закрытии приложения",
            variable=self._confirm_exit_var,
            command=self._on_confirm_exit_toggle,
        ).grid(
            row=0, column=0, columnspan=2,
            sticky="w", padx=12, pady=(8, 4),
        )

        ctk.CTkLabel(
            section,
            text=(
                "Если включено, при попытке закрыть окно появится "
                "запрос на подтверждение."
            ),
            anchor="w",
            justify="left",
            wraplength=520,
            text_color=("gray40", "gray60"),
            font=get_font(_HINT_FONT_SIZE),
        ).grid(
            row=1, column=0, columnspan=2,
            sticky="w", padx=12, pady=(0, 10),
        )

        self._hash_cache_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            section,
            text="Использовать кэш хэшей при сравнении файлов",
            variable=self._hash_cache_var,
            command=self._on_hash_cache_toggle,
        ).grid(
            row=2, column=0, columnspan=2,
            sticky="w", padx=12, pady=(8, 4),
        )

        ctk.CTkLabel(
            section,
            text=(
                "Ускоряет повторные копирования: файлы сравниваются "
                "по размеру и времени изменения, хэш пересчитывается "
                "только при изменениях. Отключите, если нужна "
                "побайтовая сверка при каждом запуске."
            ),
            anchor="w",
            justify="left",
            wraplength=520,
            text_color=("gray40", "gray60"),
            font=get_font(_HINT_FONT_SIZE),
        ).grid(
            row=3, column=0, columnspan=2,
            sticky="w", padx=12, pady=(0, 10),
        )

    # --- Секция: Данные ---

    def _build_data_section(self) -> None:
        section = self._make_section("Данные приложения")

        ctk.CTkLabel(
            section, text="Файл настроек:", anchor="w",
            font=get_font(_BODY_FONT_SIZE),
        ).grid(row=0, column=0, sticky="nw", padx=12, pady=8)

        self._path_entry = ctk.CTkEntry(section, state="readonly")
        self._path_entry.grid(
            row=0, column=1, sticky="ew", padx=(0, 12), pady=8,
        )
        section.grid_columnconfigure(1, weight=1)
        enable_clipboard(self._path_entry)

        ctk.CTkLabel(
            section,
            text=(
                "Все настройки и профили хранятся в одном файле "
                "в папке «Документы». Файл зашифрован средствами "
                "Windows (DPAPI) и привязан к текущему пользователю."
            ),
            anchor="w",
            justify="left",
            wraplength=520,
            text_color=("gray40", "gray60"),
            font=get_font(_HINT_FONT_SIZE),
        ).grid(
            row=1, column=0, columnspan=2,
            sticky="w", padx=12, pady=(0, 8),
        )

        StyledButton(
            section, text="Открыть папку",
            variant=VARIANT_SECONDARY, width=_ROW_BUTTON_WIDTH,
            command=self._on_open_folder,
        ).grid(
            row=2, column=0, columnspan=2,
            sticky="w", padx=12, pady=(0, 12),
        )

    # --- Секция: Сброс ---

    def _build_reset_section(self) -> None:
        section = self._make_section("Сброс настроек")

        ctk.CTkLabel(
            section,
            text=(
                "Удаляет все профили и возвращает настройки к "
                "значениям по умолчанию. Действие нельзя отменить."
            ),
            anchor="w",
            justify="left",
            wraplength=520,
            text_color=("gray40", "gray60"),
            font=get_font(_HINT_FONT_SIZE),
        ).grid(
            row=0, column=0, columnspan=2,
            sticky="w", padx=12, pady=(8, 8),
        )

        StyledButton(
            section, text="Сбросить все настройки",
            variant=VARIANT_DANGER, width=_ROW_BUTTON_WIDTH,
            command=self._on_reset_all,
        ).grid(
            row=1, column=0, columnspan=2,
            sticky="w", padx=12, pady=(0, 12),
        )

    # --- Секция: О программе ---

    def _build_about_section(self) -> None:
        section = self._make_section("О программе")

        ctk.CTkLabel(
            section,
            text=f"{APP_NAME}",
            anchor="w",
            font=get_font(_BODY_FONT_SIZE, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            section,
            text=f"Версия {APP_VERSION}",
            anchor="w",
            text_color=("gray40", "gray60"),
            font=get_font(_HINT_FONT_SIZE),
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 12))

    # --- Утилита: каркас секции ---

    def _make_section(self, title: str) -> ctk.CTkFrame:
        """Создаёт визуальный блок с заголовком и возвращает тело."""
        header = ctk.CTkLabel(
            self._scroll,
            text=title,
            anchor="w",
            font=get_font(_SECTION_FONT_SIZE, "bold"),
        )
        header.grid(
            sticky="w", padx=4, pady=(_SECTION_PADY_TOP, 4),
        )

        body = ctk.CTkFrame(self._scroll)
        body.grid(sticky="ew", padx=0, pady=(0, 8))
        body.grid_columnconfigure(1, weight=1)

        sep = make_separator(self._scroll)
        sep.grid(sticky="ew", padx=4, pady=SEPARATOR_PADY)

        return body

    # --- Синхронизация с настройками ---

    def _sync_from_settings(self) -> None:
        s = self.window.settings

        self._theme_var.set(
            THEME_LABELS.get(s.theme, THEME_LABELS["system"]),
        )
        self._confirm_exit_var.set(bool(s.confirm_on_exit))
        self._hash_cache_var.set(bool(s.hash_cache_enabled))

        try:
            path = str(get_settings_path())
        except Exception as exc:
            logger.debug(
                "Не удалось получить путь settings.dat: %r", exc,
            )
            path = "—"
        self._set_readonly_text(self._path_entry, path)

    @staticmethod
    def _set_readonly_text(entry: ctk.CTkEntry, value: str) -> None:
        entry.configure(state="normal")
        entry.delete(0, "end")
        if value:
            entry.insert(0, value)
        entry.configure(state="readonly")

    # --- Обработчики ---

    def _on_theme_change(self, label: str) -> None:
        key = _label_to_theme_key(label)
        if key is None:
            logger.warning("Неизвестная тема: %r", label)
            return

        self.window.settings.theme = key
        apply_theme(key)
        self.window.save_settings_now()
        self.window.set_status(f"Тема изменена: {label}")

    def _on_confirm_exit_toggle(self) -> None:
        enabled = bool(self._confirm_exit_var.get())
        self.window.settings.confirm_on_exit = enabled
        self.window.save_settings_now()
        state = "включено" if enabled else "выключено"
        self.window.set_status(f"Подтверждение выхода {state}")

    def _on_hash_cache_toggle(self) -> None:
        enabled = bool(self._hash_cache_var.get())
        self.window.settings.hash_cache_enabled = enabled
        self.window.save_settings_now()
        state = "включён" if enabled else "выключен"
        self.window.set_status(f"Кэш хэшей {state}")

    def _on_open_folder(self) -> None:
        path = get_settings_path()
        folder = path.parent

        if not folder.exists():
            show_info(
                self.window,
                "Папка не создана",
                (
                    f"Папка ещё не создана:\n{folder}\n\n"
                    f"Она появится после первого сохранения настроек."
                ),
                parent_visible=self.window.state() in (
                    "normal", "zoomed",
                ),
            )
            return

        try:
            if path.exists():
                subprocess.Popen(
                    ["explorer", "/select,", str(path)],
                )
            else:
                subprocess.Popen(["explorer", str(folder)])
        except OSError as exc:
            logger.error("Не удалось открыть папку: %r", exc)
            show_error(
                self.window,
                "Не удалось открыть папку",
                f"Путь: {folder}\nОшибка: {exc}",
            )
            return

        self.window.set_status(f"Открыто: {folder}")

    def _on_reset_all(self) -> None:
        parent_visible = self.window.state() in ("normal", "zoomed")

        confirmed = ask_yes_no(
            self.window,
            "Сброс всех настроек",
            (
                "Сбросить все настройки и удалить все профили?\n\n"
                "Действие нельзя отменить. Файл настроек будет "
                "перезаписан значениями по умолчанию."
            ),
            yes_text="Сбросить всё",
            no_text="Отмена",
            parent_visible=parent_visible,
        )
        if not confirmed:
            return

        self.window.reset_all_settings()


def _label_to_theme_key(label: str) -> str | None:
    for key, text in THEME_LABELS.items():
        if text == label:
            return key
    return None
