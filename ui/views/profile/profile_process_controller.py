"""Контроллер копирования и запуска для ProfileView."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from core import long_io
from core.models import Profile
from core.paths import ensure_directory, to_long_path
from core.settings_store import save_settings
from services.copy.copy_service import (
    PHASE_SAVE_SCAN,
    PHASE_SAVE_STORE,
    CopyResult,
    format_copy_status,
    format_mirror_suffix,
)
from services.system.launcher import LaunchError, launch_exe
from ui.dialogs import show_error
from ui.views.profile.profile_paths import (
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

        src_err = source_error(profile.source)
        if src_err is not None:
            self._show_copy_blocked(src_err)
            self._on_reload()
            return

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

        conflict = path_conflict_error(
            profile.source, profile.destination,
        )
        if conflict is not None:
            self._show_copy_blocked(
                f"{conflict}.\n\n"
                f"Измените исходную или целевую директорию."
            )
            return

        if not self._window.ensure_disk_space(
            profile.source, profile.destination,
            profile.create_backup,
        ):
            return

        self._on_busy_change(True)
        self._window.set_status_progress("Копирование…", 0.0)

        started = self._window.start_copy_with_ui(
            source=profile.source,
            destination=profile.destination,
            create_backup=profile.create_backup,
            hash_cache_enabled=(
                self._window.settings.hash_cache_enabled
            ),
            mirror_mode=profile.mirror_mode,
            profile_name=profile.display_name,
            is_startup_check=False,
            on_progress=self._on_copy_progress,
            on_done=lambda r, p=profile: self._on_copy_done(r, p),
            on_error=self._on_copy_error,
        )
        if not started:
            self._on_busy_change(False)

    def _on_copy_progress(self, progress) -> None:
        if progress.phase == PHASE_SAVE_SCAN:
            self._window.set_status_progress(
                f"Сканирование: "
                f"{progress.processed}/{progress.total}",
                progress.percent / 100.0,
            )
            return
        if progress.phase == PHASE_SAVE_STORE:
            self._window.set_status_progress(
                f"Сохранение в хранилище: "
                f"{progress.processed}/{progress.total}",
                progress.percent / 100.0,
            )
            return

        self._window.set_status_progress(
            f"Копирование: {progress.processed}/{progress.total}",
            progress.percent / 100.0,
        )

    def _on_copy_done(
        self, result: CopyResult, profile: Profile,
    ) -> None:
        self._on_busy_change(False)

        text = format_copy_status(result)
        text += format_mirror_suffix(result)
        self._window.set_status_progress(text, None)

        if result.cancelled:
            return

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

        # long_io.isfile понимает `\\?\`; Path.is_file — нет.
        if not long_io.isfile(to_long_path(full)):
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
