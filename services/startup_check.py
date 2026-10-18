"""Очередь автопроверки директорий при старте приложения."""

from __future__ import annotations

from collections.abc import Callable

from core.models import Profile
from core.settings_store import save_settings
from services.copy_service import CopyResult, CopyService
from ui.views.profile.profile_paths import ensure_directory
from utils.logger import get_logger

logger = get_logger(__name__)

_NEXT_DELAY_MS = 80


class StartupCheckQueue:
    """Последовательная очередь автопроверки."""

    def __init__(
        self,
        window,
        copy_service: CopyService,
        set_status_progress: Callable[[str, float | None], None],
        on_finish: Callable[[], None],
    ):
        self._window = window
        self._copy_service = copy_service
        self._set_status_progress = set_status_progress
        self._on_finish = on_finish

        self._queue: list[Profile] = []
        self._total = 0
        self._index = 0
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, profiles: list[Profile]) -> None:
        if self._running:
            logger.debug("StartupCheckQueue уже запущена")
            return

        candidates = [
            p for p in profiles
            if p.check_on_startup and p.can_copy()
        ]
        if not candidates:
            return

        candidates.sort(
            key=lambda p: p.last_used_at or "", reverse=True,
        )

        self._queue = list(candidates)
        self._total = len(candidates)
        self._index = 0
        self._running = True

        logger.info(
            "Автопроверка: %d профил(ей) в очереди", self._total,
        )
        self._process_next()

    def cancel(self) -> None:
        if not self._running:
            return
        self._queue.clear()
        self._running = False
        logger.info("Автопроверка: очередь отменена")

    def _process_next(self) -> None:
        if not self._running:
            return

        if not self._queue:
            self._running = False
            self._set_status_progress("Автопроверка завершена", None)
            logger.info("Автопроверка: всё завершено")
            self._on_finish()
            return

        profile = self._queue.pop(0)
        self._index += 1

        # Пересоздаём destination, если он пропал — как при обычном
        # копировании.
        if not ensure_directory(profile.destination):
            logger.warning(
                "Автопроверка %s: не удалось создать %s",
                profile.display_name, profile.destination,
            )
            self._window.after(_NEXT_DELAY_MS, self._process_next)
            return

        header = (
            f"Автопроверка {self._index}/{self._total}: "
            f"{profile.display_name}"
        )
        self._set_status_progress(header, 0.0)

        started = self._copy_service.start(
            source=profile.source,
            destination=profile.destination,
            create_backup=profile.create_backup,
            on_progress=self._on_progress,
            on_done=lambda r, p=profile: self._on_done(r, p),
            on_error=lambda msg, p=profile: self._on_error(msg, p),
        )
        if not started:
            logger.warning(
                "Автопроверка: профиль %s пропущен (start=False)",
                profile.display_name,
            )
            self._window.after(_NEXT_DELAY_MS, self._process_next)

    def _on_progress(self, progress) -> None:
        header = f"Автопроверка {self._index}/{self._total}"
        self._set_status_progress(
            header, progress.percent / 100.0,
        )

    def _on_done(self, result: CopyResult, profile: Profile) -> None:
        if not self._running:
            return

        if result.cancelled:
            logger.info("Автопроверка прервана")
            self._queue.clear()
            self._running = False
            return

        profile.touch()
        save_settings(self._window.settings)

        logger.info(
            "Автопроверка %s: скопировано %d, пропущено %d, "
            "ошибок %d",
            profile.display_name,
            result.copied, result.skipped, result.errors,
        )

        self._window.after(_NEXT_DELAY_MS, self._process_next)

    def _on_error(self, message: str, profile: Profile) -> None:
        if not self._running:
            return

        logger.error(
            "Автопроверка %s: %s", profile.display_name, message,
        )

        self._window.after(_NEXT_DELAY_MS, self._process_next)
