"""Контроллер копирования и запуска для ProfileView.

Перед копированием destination пересоздаётся, если его нет на
диске (путь при этом должен быть задан). Source пересоздавать
бессмысленно — данные потеряны, показываем ошибку.

View передаёт три callback:
  • get_profile()    — получить текущий профиль (или None);
  • on_busy_change() — изменить состояние «занято» и перерисовать
                        кнопки;
  • on_reload()      — перерисовать форму после завершения.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from core.models import Profile
from core.settings_store import save_settings
from services.copy_service import CopyResult, format_cancel_status
from services.launcher import LaunchError, launch_exe
from ui.dialogs import show_error
from ui.views.profile.profile_paths import (
    ensure_directory,
    path_conflict_error,
    source_error,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class ProfileProcessController:
    """Копирование и запуск приложения для текущего профиля."""

    def __init__(
        self,
        window,
        *,
        get_profile: Callable[[], Profile | None],
        on_busy_change: Callable[[bool], None],
        on_reload: Callable[[], None],
    ):
        self._window = window
        self._get_profile = get_profile
        self._on_busy_change = on_busy_change
        self._on_reload = on_reload

    # --- Копирование ---

    def copy(self) -> None:
        profile = self._get_profile()
        if profile is None:
            return

        # 1. Source должен существовать. Пересоздавать бессмысленно:
        #    пустая исходная папка означает «нечего копировать».
        src_err = source_error(profile.source)
        if src_err is not None:
            self._show_copy_blocked(src_err)
            self._on_reload()
            return

        # 2. Destination должен быть задан. Если папки нет на диске
        #    — пересоздаём.
        if not profile.destination:
            self._show_copy_blocked("Целевая директория не задана.")
            self._on_reload()
            return

        if not ensure_directory(profile.destination):
            self._show_copy_blocked(
                "Не удалось создать целевую директорию:\n"
                f"{profile.destination}\n\n"
                "Проверьте, что диск доступен и есть права на запись."
            )
            self._on_reload()
            return

        # 3. Конфликт путей.
        conflict = path_conflict_error(
            profile.source, profile.destination,
        )
        if conflict is not None:
            self._show_copy_blocked(
                f"{conflict}.\n\n"
                f"Измените исходную или целевую директорию."
            )
            return

        # 4. Старт.
        self._on_busy_change(True)
        self._window.set_status_progress("Копирование…", 0.0)

        started = self._window.copy_service.start(
            source=profile.source,
            destination=profile.destination,
            create_backup=profile.create_backup,
            on_progress=self._on_copy_progress,
            on_done=lambda r, p=profile: self._on_copy_done(r, p),
            on_error=self._on_copy_error,
            hash_cache_enabled=(
                self._window.settings.hash_cache_enabled
            ),
        )
        if not started:
            self._on_busy_change(False)

    def _on_copy_progress(self, progress) -> None:
        self._window.set_status_progress(
            f"Копирование: {progress.processed}/{progress.total}",
            progress.percent / 100.0,
        )

    def _on_copy_done(
        self, result: CopyResult, profile: Profile,
    ) -> None:
        self._on_busy_change(False)

        if result.cancelled:
            self._window.set_status_progress(
                format_cancel_status(result), None,
            )
            return

        parts = [
            f"скопировано {result.copied}",
            f"пропущено {result.skipped}",
        ]
        if result.errors:
            parts.append(f"ошибок {result.errors}")
        text = "Копирование завершено: " + ", ".join(parts)
        self._window.set_status_progress(text, None)

        if result.backup_dir:
            self._window.set_status(
                f"{text}  ·  бэкап: {Path(result.backup_dir).name}",
            )

        profile.touch()
        save_settings(self._window.settings)
        self._on_reload()

        if profile.run_after_copy and result.errors == 0:
            self.run()

    def _on_copy_error(self, message: str) -> None:
        self._on_busy_change(False)
        self._window.set_status_progress(
            f"Ошибка копирования: {message}", None,
        )
        show_error(
            self._window,
            "Ошибка копирования",
            message,
        )

    def _show_copy_blocked(self, message: str) -> None:
        show_error(
            self._window,
            "Нельзя запустить копирование",
            message,
        )

    # --- Запуск ---

    def run(self) -> None:
        profile = self._get_profile()
        if profile is None:
            return

        full = profile.exe_full_path()
        if not full:
            show_error(
                self._window,
                "Нельзя запустить приложение",
                "Приложение не выбрано в профиле.",
            )
            return

        if not Path(full).is_file():
            show_error(
                self._window,
                "Нельзя запустить приложение",
                (
                    "Файл приложения не найден:\n"
                    f"{full}\n\n"
                    "Сначала выполните копирование."
                ),
            )
            self._on_reload()
            return

        try:
            launch_exe(full)
            profile.touch()
            save_settings(self._window.settings)
            self._window.set_status(
                f"Запущено: {Path(full).name}",
            )
        except LaunchError as exc:
            self._window.set_status(f"Ошибка запуска: {exc}")
            show_error(
                self._window,
                "Ошибка запуска",
                str(exc),
            )
