"""Фоновый опрос папок-источников и уведомления об изменениях.

Один daemon-поток на приложение, профили обходятся
последовательно — без пула потоков и без параллельного I/O.
Это осознанный компромисс ради «тихого» режима: опрос идёт
редко (по умолчанию раз в 5 минут) и только через `stat`.

Логика одного цикла (`run_once`) полностью синхронна и
тестируема без потоков и `sleep`:

  1. Проверить, что уведомления включены и есть кандидаты.
  2. Для каждого профиля (последовательно):
     - пропустить, если идёт копирование/восстановление;
     - построить текущий снимок источника (stat-only);
     - сравнить с сохранённым снимком;
     - если `check_periodically` включён и есть изменения,
       вызвать колбэк для периодического копирования;
     - прочитать `!CCRun/message.txt`, сравнить sha256;
     - обновить базу **до** показа уведомления (дедупликация);
     - накопить `ProfileDigest`.
  3. Собрать одно (или несколько) уведомлений и показать.

Первый цикл для профиля только создаёт базу — иначе
уведомление сообщило бы «изменилось всё».

`message.txt` с одними комментариями (строки с `#`) считается
пустым: `sha256` обновляется, уведомление не показывается.
Так шаблон, созданный кнопкой «Создать message.txt», не
выглядит как сообщение, но и не приводит к повторному чтению
каждый цикл.

Показ уведомлений:
  • `notify_aggregate=True` — одно уведомление со списком
    всех профилей с новостями (не больше
    `NOTIFY_AGGREGATE_MAX_ITEMS` строк внутри).
  • `notify_aggregate=False` — split-режим: до
    `NOTIFY_SPLIT_MAX_DETAILED` подробных тостов (последние
    в порядке обхода), и если профилей с новостями больше —
    один обобщающий «Проверьте папки источников» с числом
    скрытых. Всего не больше 4 тостов.

Для одиночного уведомления о сообщении в `ProfileDigest`
кладётся `message_file_path` — тост показывает кнопку
«Открыть».
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from config.constants import (
    MONITOR_INTERVAL_DEFAULT,
    MONITOR_INTERVAL_MAX,
    MONITOR_INTERVAL_MIN,
    NOTIFY_SPLIT_MAX_DETAILED,
)
from core import long_io
from core.models import AppSettings, Profile
from services.monitor.message_file import (
    message_path,
    read_message,
)
from services.monitor.monitor_state import (
    MonitorEntry,
    MonitorStore,
)
from services.monitor.source_snapshot import (
    build_snapshot,
    diff_snapshots,
)
from services.system.notifier import (
    Notification,
    Notifier,
    ProfileDigest,
    format_profile_notification,
    format_split_summary,
)
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "MonitorService",
    "clamp_interval",
]

_MIN_SLEEP_SEC = 1.0


@dataclass
class MonitorRunResult:
    """Итог одного цикла опроса (для тестов и логов)."""

    checked: int = 0
    with_changes: int = 0
    notifications: int = 0
    skipped_busy: int = 0
    skipped_unavailable: int = 0


def clamp_interval(minutes: int) -> int:
    """Ограничивает интервал допустимыми границами."""
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return MONITOR_INTERVAL_DEFAULT
    return max(MONITOR_INTERVAL_MIN, min(MONITOR_INTERVAL_MAX, value))


class MonitorService:
    """Опрос источников в одном фоновом потоке."""

    def __init__(
        self,
        *,
        notifier: Notifier,
        store: MonitorStore | None = None,
        is_busy: Callable[[str], bool] | None = None,
        on_periodic_copy: Callable[[Profile], None] | None = None,
        scheduler: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        """
        Args:
            notifier: Провайдер показа уведомлений.
            store: База снимков (по умолчанию — Documents).
            is_busy: `True`, если по профилю сейчас идёт
                копирование/восстановление.
            on_periodic_copy: Колбэк для запуска копирования,
                если у профиля включён `check_periodically` и
                есть изменения.
            scheduler: Маршалинг в UI-поток (необязателен:
                уведомления показываются прямо из потока).
        """
        self._notifier = notifier
        self._store = store or MonitorStore()
        self._is_busy = is_busy or (lambda _pid: False)
        self._on_periodic_copy = on_periodic_copy or (lambda _p: None)
        self._schedule = scheduler

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._profiles: list[Profile] = []
        self._settings = AppSettings()
        self._interval_min = MONITOR_INTERVAL_DEFAULT

        self._last_result = MonitorRunResult()
        self._last_run_at = 0.0

    # --- Управление ---

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def last_run_at(self) -> float:
        return self._last_run_at

    @property
    def interval_min(self) -> int:
        return self._interval_min

    def configure(
        self,
        profiles: Iterable[Profile],
        settings: AppSettings,
    ) -> None:
        """Обновляет набор профилей и настройки.

        Безопасно вызывать на ходу: поток читает «свежий»
        конфиг в начале каждого цикла.
        """
        with self._lock:
            self._profiles = list(profiles)
            self._settings = settings
            self._interval_min = clamp_interval(
                settings.monitor_interval_min,
            )
        self._wake_event.set()

    def start(self) -> bool:
        """Запускает поток. `False`, если уже запущен."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if not self._settings.notifications_enabled:
                logger.debug(
                    "MonitorService: уведомления выключены — не стартуем",
                )
                return False

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="SourceMonitor",
                daemon=True,
            )
            self._thread.start()
        logger.info(
            "Мониторинг источника запущен (интервал %d мин)",
            self._interval_min,
        )
        return True

    def stop(self) -> None:
        """Останавливает поток и дожидается его завершения."""
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is None:
            return

        self._stop_event.set()
        self._wake_event.set()
        thread.join(timeout=self._join_timeout())
        logger.info("Мониторинг источника остановлен")

    def wake(self) -> None:
        """Просит поток выполнить цикл немедленно."""
        self._wake_event.set()

    def reset_profile(self, profile_id: str) -> None:
        """Сбрасывает базу профиля (например, после копирования).

        Следующий цикл только пересоздаст снимок, не показывая
        уведомление о том, что пользователь только что скопировал.
        """
        self._store.clear(profile_id)
        logger.debug(
            "MonitorService: база профиля %s сброшена", profile_id,
        )

    # --- Цикл ---

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                logger.error(
                    "Мониторинг: цикл упал: %r", exc, exc_info=True,
                )

            timeout_sec = max(
                _MIN_SLEEP_SEC, self._interval_min * 60.0,
            )
            self._wake_event.wait(timeout=timeout_sec)
            self._wake_event.clear()

    def run_once(self) -> MonitorRunResult:
        """Один цикл опроса. Синхронный и тестируемый.

        Первый цикл по профилю только создаёт базу снимков:
        уведомление «изменилось всё» не показывается.
        """
        profiles, settings, interval = self._snapshot_config()
        result = MonitorRunResult()

        if not settings.notifications_enabled:
            return result

        candidates = [
            p for p in profiles if self._wants_monitoring(p, settings)
        ]
        self._store.prune({p.id for p in profiles})

        digests: list[ProfileDigest] = []
        for profile in candidates:
            if self._stop_event.is_set():
                break

            if self._is_busy(profile.id):
                result.skipped_busy += 1
                logger.debug(
                    "Мониторинг %s: занят — пропуск",
                    profile.display_name,
                )
                continue

            digest = self._check_profile(profile, settings, result)
            if digest is not None:
                digests.append(digest)

        self._last_result = result
        self._last_run_at = time.time()
        self._interval_min = interval

        if digests:
            self._emit(digests, settings, result)
        return result

    def _snapshot_config(
        self,
    ) -> tuple[list[Profile], AppSettings, int]:
        with self._lock:
            return (
                list(self._profiles),
                self._settings,
                self._interval_min,
            )

    @staticmethod
    def _wants_monitoring(
        profile: Profile, settings: AppSettings,
    ) -> bool:
        """Профиль вообще участвует в опросе.

        Доступность источника здесь намеренно не проверяется:
        пропавший источник должен попасть в статистику
        `skipped_unavailable`, а не молча исчезнуть из обхода.
        """
        if not profile.source:
            return False
        if profile.check_periodically:
            return True
        if settings.notify_source_changes and profile.notify_on_changes:
            return True
        if settings.notify_message and profile.notify_on_message:
            return True
        return False

    def _check_profile(
        self,
        profile: Profile,
        settings: AppSettings,
        result: MonitorRunResult,
    ) -> ProfileDigest | None:
        """Проверяет один профиль. Возвращает digest при новостях."""
        result.checked += 1

        if not long_io.isdir(profile.source):
            result.skipped_unavailable += 1
            logger.debug(
                "Мониторинг %s: источник недоступен (%s)",
                profile.display_name, profile.source,
            )
            return None

        loaded = self._store.load(profile.id)
        entry = self._entry_for(loaded, profile)
        digest = ProfileDigest(profile_name=profile.display_name)
        changed = False

        need_diff = (
            (settings.notify_source_changes and profile.notify_on_changes)
            or profile.check_periodically
        )

        if need_diff:
            current = build_snapshot(profile.source)
            if current is None:
                result.skipped_unavailable += 1
                logger.debug(
                    "Мониторинг %s: снимок не построен",
                    profile.display_name,
                )
                return None

            # Базу «чужого» источника не сравниваем: после смены
            # source всё содержимое выглядело бы как удаления.
            previous = (
                loaded.snapshot
                if loaded is not None
                and loaded.source == profile.source
                else None
            )

            has_changes = False
            if previous is not None:
                diff = diff_snapshots(previous, current)
                if diff.has_changes:
                    has_changes = True
                    if (
                        settings.notify_source_changes
                        and profile.notify_on_changes
                    ):
                        digest.added = diff.added
                        digest.modified = diff.modified
                        digest.removed = diff.removed
                        changed = True

            entry.snapshot = current

            if profile.check_periodically and has_changes:
                logger.info(
                    "Мониторинг %s: периодическое копирование",
                    profile.display_name,
                )
                self._on_periodic_copy(profile)

        if settings.notify_message and profile.notify_on_message:
            message = read_message(profile.source)
            if (
                message.sha256
                and message.sha256 != entry.message_sha256
            ):
                if message.preview:
                    digest.message_preview = message.preview
                    digest.message_truncated = message.truncated
                    digest.message_file_path = message_path(
                        profile.source,
                    )
                    changed = True
            entry.message_sha256 = message.sha256

        self._store.save(entry)

        if not changed:
            return None

        if not (digest.has_changes or digest.has_message):
            return None

        result.with_changes += 1
        logger.info(
            "Мониторинг %s: изменения (+%d ~%d -%d), сообщение: %s",
            profile.display_name,
            digest.added, digest.modified, digest.removed,
            "есть" if digest.has_message else "нет",
        )
        return digest

    def _entry_for(
        self,
        entry: MonitorEntry | None,
        profile: Profile,
    ) -> MonitorEntry:
        """Существующая запись или новая (при смене source — новая)."""
        if entry is not None and entry.source == profile.source:
            return entry
        return MonitorEntry(
            profile_id=profile.id, source=profile.source,
        )

    def _emit(
        self,
        digests: list[ProfileDigest],
        settings: AppSettings,
        result: MonitorRunResult,
    ) -> None:
        """Показ уведомлений: агрегированно или раздельно."""
        if settings.notify_aggregate:
            notification = format_profile_notification(
                digests, aggregate=True,
            )
            if notification is None:
                return
            notification.auto_close_sec = (
                settings.notify_auto_close_sec
            )
            self._show(notification)
            result.notifications = 1
            return

        limit = NOTIFY_SPLIT_MAX_DETAILED
        detailed = digests[-limit:] if len(digests) > limit else digests
        skipped = len(digests) - len(detailed)

        shown = 0
        for digest in detailed:
            notification = format_profile_notification(
                [digest], aggregate=False,
            )
            if notification is None:
                continue
            notification.auto_close_sec = (
                settings.notify_auto_close_sec
            )
            self._show(notification)
            shown += 1

        if skipped > 0:
            summary = format_split_summary(skipped)
            summary.auto_close_sec = (
                settings.notify_auto_close_sec
            )
            self._show(summary)
            shown += 1

        result.notifications = shown

    def _show(self, notification: Notification) -> None:
        if self._schedule is not None:
            self._schedule(
                lambda: self._notifier.notify(notification),
            )
            return
        try:
            self._notifier.notify(notification)
        except Exception as exc:
            logger.error(
                "Мониторинг: показ уведомления: %r", exc, exc_info=True,
            )

    @staticmethod
    def _join_timeout() -> float:
        return 5.0
