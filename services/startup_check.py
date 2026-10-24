"""Очередь автопроверки директорий при старте приложения.

Перед запуском копирования для каждого профиля с
check_on_startup=True очередь проверяет:
  • если профиль восстановлен из бэкапа
    (current.last_action == "restore") и настройка
    run_autocheck_on_restored=False — профиль пропускается
    (защита восстановленных файлов от перезаписи новыми из
    источника; mirror в таком случае не запускается и
    диалог подтверждения не показывается);
  • иначе — выполняется как обычно, включая mirror.

Список кандидатов и количество пропущенных возвращает
select_startup_candidates — чистая функция, тестируется
без Tk.

Пользователь может разрешить автопроверку для
восстановленных профилей в Настройках (чекбокс «Выполнять
автопроверку при запуске для профилей, восстановленных из
бэкапа»). Ручной copy (кнопка «Копировать» или ▶ в сайдбаре)
всегда работает как обычно — эта настройка только про
автозапуск.
"""

from __future__ import annotations

from collections.abc import Callable

from core.models import Profile
from core.paths import ensure_directory
from core.settings_store import save_settings
from services.cas.current_pointer import CurrentPointer
from services.copy.copy_service import (
    CopyResult,
    CopyService,
    format_cancel_status,
)
from services.restore.disk_space import check_disk_space, format_bytes
from utils.logger import get_logger

logger = get_logger(__name__)

_NEXT_DELAY_MS = 80


def _is_restored(destination: str) -> bool:
    """True, если destination восстановлен из бэкапа
    (current.last_action == "restore")."""
    if not destination:
        return False
    try:
        cur = CurrentPointer(destination).load()
    except Exception as exc:
        logger.debug("_is_restored(%r): %r", destination, exc)
        return False
    return cur is not None and cur.last_action == "restore"


def select_startup_candidates(
    profiles: list[Profile], *, run_on_restored: bool,
) -> tuple[list[Profile], int]:
    """Отбирает профили для автопроверки.

    Возвращает (candidates, skipped_restored_count).
    skipped_restored_count — сколько профилей с
    check_on_startup=True пропущено, потому что они
    восстановлены из бэкапа, а run_on_restored=False.
    """
    candidates: list[Profile] = []
    skipped = 0
    for p in profiles:
        if not p.check_on_startup or not p.can_copy():
            continue
        if not run_on_restored and _is_restored(p.destination):
            skipped += 1
            continue
        candidates.append(p)
    return candidates, skipped


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
        self._skipped_restored = 0

    @property
    def is_running(self) -> bool:
        return self._running

    def start(
        self,
        profiles: list[Profile],
        *,
        run_on_restored: bool,
    ) -> None:
        if self._running:
            logger.debug("StartupCheckQueue уже запущена")
            return

        self._skipped_restored = 0
        candidates, self._skipped_restored = (
            select_startup_candidates(
                profiles, run_on_restored=run_on_restored,
            )
        )

        if not candidates:
            if self._skipped_restored:
                self._set_status_progress(
                    self._format_skip_only(
                        self._skipped_restored,
                    ),
                    None,
                )
                logger.info(
                    "Автопроверка: %d профил(ей) пропущено "
                    "(восстановлены из бэкапа)",
                    self._skipped_restored,
                )
                self._on_finish()
            return

        candidates.sort(
            key=lambda p: p.last_used_at or "", reverse=True,
        )

        self._queue = list(candidates)
        self._total = len(candidates)
        self._index = 0
        self._running = True

        if self._skipped_restored:
            logger.info(
                "Автопроверка: %d профил(ей) в очереди, "
                "пропущено %d восстановленных",
                self._total, self._skipped_restored,
            )
        else:
            logger.info(
                "Автопроверка: %d профил(ей) в очереди",
                self._total,
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
            self._set_status_progress(
                self._format_finished(), None,
            )
            logger.info("Автопроверка: всё завершено")
            self._on_finish()
            return

        profile = self._queue.pop(0)
        self._index += 1

        if not ensure_directory(profile.destination):
            logger.warning(
                "Автопроверка %s: не удалось создать %s",
                profile.display_name, profile.destination,
            )
            self._window.after(_NEXT_DELAY_MS, self._process_next)
            return

        check = check_disk_space(
            profile.source,
            profile.destination,
            profile.create_backup,
        )
        if check is not None and not check.ok:
            logger.warning(
                "Автопроверка %s: недостаточно места "
                "(нужно %s, доступно %s) — пропуск",
                profile.display_name,
                format_bytes(check.needed_bytes),
                format_bytes(check.available_bytes),
            )
            self._window.after(_NEXT_DELAY_MS, self._process_next)
            return

        header = (
            f"Автопроверка {self._index}/{self._total}: "
            f"{profile.display_name}"
        )
        self._set_status_progress(header, 0.0)

        started = self._window.start_copy_with_ui(
            source=profile.source,
            destination=profile.destination,
            create_backup=profile.create_backup,
            hash_cache_enabled=(
                self._window.settings.hash_cache_enabled
            ),
            mirror_mode=profile.mirror_mode,
            profile_name=profile.display_name,
            is_startup_check=True,
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
            self._set_status_progress(
                format_cancel_status(result), None,
            )
            self._on_finish()
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

    @staticmethod
    def _format_skip_only(n: int) -> str:
        return (
            f"Автопроверка: пропущено {n} "
            f"(восстановлены из бэкапа)"
        )

    def _format_finished(self) -> str:
        msg = "Автопроверка завершена"
        if self._skipped_restored:
            msg += (
                f"  ·  пропущено {self._skipped_restored} "
                f"(восстановлены из бэкапа)"
            )
        return msg
