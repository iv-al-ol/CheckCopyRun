"""Контроллер путей профиля: выбор source/destination/exe, открытие папок.

Не хранит состояние — работает с текущим профилем через callback
get_profile(). Сохранение и перерисовку делает View через
on_changed(); обновление состояния кнопок — через on_state_refresh().

Логика выбора — в profile_paths. Здесь только связывание:
диалог → проверка → запись в profile → notify.

Извлечение иконки из exe обёрнуто в защиту — если оно падает,
выбор exe всё равно сохраняется.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from core.models import Profile
from core.paths import ensure_directory
from core.settings_store import get_icons_dir
from services.system.icon_extractor import save_exe_icon
from ui.dialogs import show_error
from ui.views.profile.profile_paths import (
    open_folder_in_explorer,
    path_conflict_error,
    pick_destination_directory,
    pick_exe_file,
    pick_source_directory,
    resolve_destination_target,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class ProfilePathController:
    """Диалоги выбора путей и открытие папок для ProfileView."""

    def __init__(
        self,
        window,
        *,
        get_profile: Callable[[], Profile | None],
        on_changed: Callable[[], None],
        on_state_refresh: Callable[[], None],
    ):
        self._window = window
        self._get_profile = get_profile
        self._on_changed = on_changed
        self._on_state_refresh = on_state_refresh

    # --- Выбор путей ---

    def pick_source(self) -> None:
        profile = self._get_profile()
        if profile is None:
            return

        new_source = pick_source_directory(
            self._window, profile.source,
        )
        if not new_source:
            return

        conflict = path_conflict_error(
            new_source, profile.destination,
        )
        if conflict:
            self._show_conflict(conflict, "папку-источник")
            return

        profile.source = new_source
        profile.exe_relative = ""
        self._on_changed()

    def pick_destination(self) -> None:
        profile = self._get_profile()
        if profile is None:
            return

        abs_path = pick_destination_directory(
            self._window, profile.destination,
        )
        if not abs_path:
            return

        conflict = path_conflict_error(profile.source, abs_path)
        if conflict:
            self._show_conflict(conflict, "папку назначения")
            return

        resolved = resolve_destination_target(
            self._window, profile.source, abs_path,
        )
        if resolved is None:
            return

        conflict = path_conflict_error(profile.source, resolved)
        if conflict:
            self._show_conflict(conflict, "папку назначения")
            return

        profile.destination = resolved
        self._on_changed()

    def pick_exe(self) -> None:
        profile = self._get_profile()
        if profile is None:
            return

        if not (profile.source and os.path.isdir(profile.source)):
            show_error(
                self._window,
                "Не выбрана исходная директория",
                (
                    "Сначала укажите папку-источник — "
                    "приложение выбирается внутри неё."
                ),
            )
            return

        abs_exe = pick_exe_file(self._window, profile.source)
        if not abs_exe:
            return

        rel = os.path.relpath(abs_exe, profile.source)
        if rel.startswith(".."):
            show_error(
                self._window,
                "Файл вне исходной директории",
                (
                    "Приложение должно находиться внутри папки "
                    f"источника. Выберите .exe из {profile.source}."
                ),
            )
            return

        # Сохраняем exe — это главное действие пользователя.
        # Извлечение иконки — дополнительное, и не должно ломать
        # основной сценарий.
        profile.exe_relative = rel

        try:
            self._maybe_set_icon_from_exe(profile)
        except Exception as exc:
            logger.error(
                "Извлечение иконки из exe не удалось: %r", exc,
            )

        self._on_changed()

    # --- Открытие папок ---

    def open_source(self) -> bool:
        profile = self._get_profile()
        if profile is None or not profile.source:
            return False

        if not ensure_directory(profile.source):
            self._on_state_refresh()
            return False

        return open_folder_in_explorer(profile.source)

    def open_destination(self) -> bool:
        profile = self._get_profile()
        if profile is None or not profile.destination:
            return False

        if not ensure_directory(profile.destination):
            self._on_state_refresh()
            return False

        return open_folder_in_explorer(profile.destination)

    # --- Вспомогательное ---

    def _show_conflict(self, conflict: str, what: str) -> None:
        show_error(
            self._window,
            "Неверная директория",
            f"{conflict}.\n\nВыберите другую {what}.",
        )

    def _maybe_set_icon_from_exe(self, profile: Profile) -> None:
        """Пытается извлечь иконку из exe. Не влияет на выбор exe."""
        if not profile.icon_auto:
            return

        full = profile.exe_source_path()
        if not full or not os.path.isfile(full):
            return

        try:
            png = save_exe_icon(Path(full), get_icons_dir())
        except Exception as exc:
            logger.error("save_exe_icon упал: %r", exc)
            return

        if png is None:
            logger.debug(
                "Иконка exe не извлечена для %s", full,
            )
            return

        profile.icon = str(png)
