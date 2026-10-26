"""Состояние диалога выбора иконки профиля — без tkinter.

Разделяет три вида выбора:
  • "emoji" — эмодзи из палитры. selected_value — эмодзи.
  • "file"  — файл-картинка (или PNG, извлечённый из выбранного exe).
              selected_value — абсолютный путь.
  • "auto"  — иконка exe самого профиля. selected_value — путь к PNG.

Приоритет пользователя: любое явное действие (клик по эмодзи,
выбор файла) выключает auto. Включить auto можно только явно через
try_enable_auto().

Тестируется без tkinter: все операции — чистые или с инъекцией
зависимостей (icons_dir, exe_icon_saver).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from config.constants import DEFAULT_PROFILE_ICON
from core.paths import looks_like_image_path
from core.settings_store import get_icons_dir
from services.system.icon_extractor import save_exe_icon
from utils.logger import get_logger

logger = get_logger(__name__)

SelectedKind = Literal["emoji", "file", "auto"]

ExeIconSaver = Callable[[Path, Path], "Path | None"]


class IconPickerState:
    """Состояние выбора иконки. Не знает про виджеты и диалоги."""

    def __init__(
        self,
        *,
        current_icon: str,
        current_icon_auto: bool,
        exe_path: Path | None,
        icons_dir: Path | None = None,
        exe_icon_saver: ExeIconSaver | None = None,
    ):
        self._exe_path = exe_path
        self._icons_dir = (
            icons_dir if icons_dir is not None else get_icons_dir()
        )
        self._exe_icon_saver = (
            exe_icon_saver if exe_icon_saver is not None
            else save_exe_icon
        )

        self._kind: SelectedKind
        self._value: str
        self._resolve_initial_state(
            current_icon=current_icon,
            current_icon_auto=current_icon_auto,
        )

    # --- Свойства ---

    @property
    def selected_kind(self) -> SelectedKind:
        return self._kind

    @property
    def selected_value(self) -> str:
        return self._value

    @property
    def is_auto(self) -> bool:
        return self._kind == "auto"

    @property
    def auto_available(self) -> bool:
        return (
            self._exe_path is not None
            and self._exe_path.is_file()
        )

    @property
    def exe_path(self) -> Path | None:
        return self._exe_path

    # --- Действия ---

    def select_emoji(self, emoji: str) -> None:
        """Пользователь выбрал эмодзи из палитры."""
        self._kind = "emoji"
        self._value = emoji or DEFAULT_PROFILE_ICON

    def select_file_as_image(self, path: str) -> None:
        """Пользователь выбрал файл-картинку."""
        self._kind = "file"
        self._value = str(Path(path).resolve())

    def select_file_from_exe(
        self, exe_path: Path,
    ) -> tuple[bool, str]:
        """Пользователь выбрал .exe вручную — извлекаем иконку.

        Возвращает (ok, error_message). При успехе state переходит
        в kind="file" со значением = путь к PNG из exe.
        """
        try:
            png = self._exe_icon_saver(exe_path, self._icons_dir)
        except Exception as exc:
            logger.error("save_exe_icon упал: %r", exc)
            return False, f"Ошибка извлечения иконки: {exc}"

        if png is None:
            return (
                False,
                f"Не удалось извлечь иконку из {exe_path.name}",
            )

        self._kind = "file"
        self._value = str(png)
        return True, ""

    def try_enable_auto(self) -> tuple[bool, str]:
        """Пытается включить auto-режим.

        Возвращает (ok, error_message). При успехе state переходит
        в kind="auto" со значением = путь к PNG из exe профиля.
        """
        if self._exe_path is None:
            return False, "Приложение не выбрано"

        if not self._exe_path.is_file():
            return (
                False,
                f"Файл приложения не найден: {self._exe_path.name}",
            )

        try:
            png = self._exe_icon_saver(self._exe_path, self._icons_dir)
        except Exception as exc:
            logger.error("save_exe_icon упал: %r", exc)
            return False, f"Ошибка извлечения иконки: {exc}"

        if png is None:
            return (
                False,
                f"Не удалось извлечь иконку из {self._exe_path.name}",
            )

        self._kind = "auto"
        self._value = str(png)
        return True, ""

    def disable_auto(self) -> None:
        """Выключает auto-режим.

        Если был auto — переходит на дефолтную эмодзи. Если уже
        эмодзи или файл — ничего не делает.
        """
        if self._kind != "auto":
            return
        self._kind = "emoji"
        self._value = DEFAULT_PROFILE_ICON

    def build_result(self) -> tuple[str, bool]:
        """Возвращает (icon, icon_auto) для сохранения в профиль."""
        if self._kind == "auto":
            return (self._value, True)
        return (self._value or DEFAULT_PROFILE_ICON, False)

    # --- Внутреннее ---

    def _resolve_initial_state(
        self,
        *,
        current_icon: str,
        current_icon_auto: bool,
    ) -> None:
        """Определяет начальный kind и value по текущему профилю."""
        # 1. auto + exe задан: если PNG уже извлечён ранее —
        #    начинаем в auto. Иначе — на дефолтной эмодзи.
        if current_icon_auto and self._exe_path is not None:
            cached = self._lookup_cached_exe_png(self._exe_path)
            if cached is not None:
                self._kind = "auto"
                self._value = str(cached)
                return
            self._kind = "emoji"
            self._value = (
                current_icon
                if not looks_like_image_path(current_icon)
                else DEFAULT_PROFILE_ICON
            )
            return

        # 2. Иконка — путь к файлу.
        if looks_like_image_path(current_icon):
            self._kind = "file"
            self._value = current_icon
            return

        # 3. Иконка — эмодзи.
        if current_icon:
            self._kind = "emoji"
            self._value = current_icon
            return

        # 4. Дефолт.
        self._kind = "emoji"
        self._value = DEFAULT_PROFILE_ICON

    def _lookup_cached_exe_png(self, exe_path: Path) -> Path | None:
        """Ищет уже извлечённый PNG для этого exe в icons_dir."""
        try:
            digest = hashlib.sha256(
                str(exe_path.resolve()).encode("utf-8"),
            ).hexdigest()[:16]
        except OSError as exc:
            logger.debug("resolve exe: %r", exc)
            return None

        candidate = self._icons_dir / f"exe_{digest}.png"
        if candidate.is_file():
            return candidate
        return None
