"""Сервис восстановления состояния из state-файла.

Механизм:
  1. Загрузить state_K.
  2. Сканировать destination → state_now.
  3. Если state_now совпадает с state_K — current → state_K,
     выйти («уже в этом состоянии»).
  4. Определить restore_point (точку возврата) с дедупликацией:
     • если state_now совпадает с current.state — переиспользуем
       его;
     • иначе ищем среди всех states state с идентичным
       содержимым — переиспользуем;
     • только если не нашли — создаём новый state
       (kind="restore_point").
  5. Построить план: build_plan(target, current).
  6. Применить: apply_plan.
  7. При отмене — откат через apply_plan из restore_point.
  8. При успехе — current → state_K.

Дедупликация устраняет разрастание точек возврата при
переключениях между резервными копиями без ручных правок:
цикл A → B → A → B не создаёт ни одного нового state-файла.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from services.blob_store import BlobStore
from services.copy_constants import STATE_KIND_RESTORE_POINT
from services.current_pointer import (
    CurrentData,
    CurrentPointer,
)
from services.hash_cache import HashCache
from services.restore_apply import apply_plan
from services.restore_planner import build_plan
from services.state_scanner import scan_destination
from services.state_store import (
    StateData,
    StateStore,
    StateStoreError,
)
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = [
    "RestoreProgress",
    "RestoreResult",
    "RestoreService",
    "format_restore_status",
]


# --- Результаты ---

@dataclass
class RestoreProgress:
    processed: int
    total: int

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 100
        return int(self.processed * 100 / self.total)


@dataclass
class RestoreResult:
    total_actions: int = 0
    restored: int = 0
    deleted_files: int = 0
    created_dirs: int = 0
    deleted_dirs: int = 0
    skipped: int = 0
    missing: int = 0
    errors: int = 0
    cancelled: bool = False
    elapsed_sec: float = 0.0

    restored_from_state: str = ""
    restore_point_path: str | None = None
    reused_restore_point: bool = False

    rollback_attempted: bool = False
    rolled_back: bool = False
    rollback_errors: int = 0


def format_restore_status(result: RestoreResult) -> str:
    if result.cancelled:
        if not result.rollback_attempted:
            return "Восстановление отменено"
        if not result.rolled_back:
            return (
                f"Восстановление отменено, откат неполный "
                f"({result.rollback_errors} ошибок) — см. лог"
            )
        return "Восстановление отменено, изменения отменены"

    if result.total_actions == 0 and result.errors == 0:
        return "Уже в этом состоянии"

    parts: list[str] = [f"восстановлено {result.restored}"]
    if result.deleted_files:
        parts.append(f"удалено файлов {result.deleted_files}")
    if result.created_dirs:
        parts.append(f"создано папок {result.created_dirs}")
    if result.deleted_dirs:
        parts.append(
            f"удалено пустых папок {result.deleted_dirs}"
        )
    if result.missing:
        parts.append(f"не найдено в хранилище {result.missing}")
    if result.errors:
        parts.append(f"ошибок {result.errors}")
    return "Восстановление завершено: " + ", ".join(parts)


# --- Воркер ---

class _RestoreWorker(threading.Thread):
    def __init__(
        self,
        backup_state_ref: str,
        destination: str,
        cancel_event: threading.Event,
        scheduler: Callable[[Callable[[], None]], None],
        on_progress: Callable[[RestoreProgress], None],
        on_done: Callable[[RestoreResult], None],
        on_error: Callable[[str], None],
    ):
        super().__init__(name="RestoreWorker", daemon=True)
        self._backup_state_ref = backup_state_ref
        self._destination = destination
        self._cancel = cancel_event
        self._schedule = scheduler
        self._on_progress = on_progress
        self._on_done = on_done
        self._on_error = on_error

        self._result = RestoreResult()
        self._last_percent = -1

        self._state_store: StateStore | None = None
        self._blobs: BlobStore | None = None
        self._current: CurrentPointer | None = None
        self._cache: HashCache | None = None

        self._target: StateData | None = None
        self._target_name: str = ""

        self._restore_point_name: str | None = None

    # --- Публичное ---

    def run(self) -> None:
        started = time.perf_counter()

        try:
            self._state_store = StateStore(self._destination)
            self._blobs = BlobStore(self._destination)
            self._current = CurrentPointer(self._destination)
            self._cache = HashCache(self._destination)
        except Exception as exc:
            logger.exception(
                "Не удалось инициализировать хранилище"
            )
            self._emit_error(
                f"Ошибка инициализации хранилища: {exc}"
            )
            return

        self._cache.load()

        if not self._load_target():
            return

        current = scan_destination(
            self._destination, self._cache,
        )
        self._populate_blobs(current)

        if self._should_skip(current, self._target):
            logger.info(
                "Restore: уже в целевом состоянии",
            )
            self._save_current(
                self._target_name, last_action="restore",
                restored_from=self._target_name,
            )
            self._result.restored_from_state = self._target_name
            self._result.elapsed_sec = (
                time.perf_counter() - started
            )
            self._emit_done()
            return

        self._resolve_restore_point(current)
        if self._restore_point_name is None:
            self._emit_error(
                "Не удалось создать точку возврата — "
                "восстановление отменено"
            )
            return

        plan = build_plan(
            self._target, current, self._blobs,
        )
        self._result.total_actions = plan.total_actions
        self._result.skipped = plan.skipped_files
        self._result.missing = len(plan.missing_blobs)

        apply_result = apply_plan(
            plan,
            self._target,
            self._destination,
            on_progress=self._on_apply_progress,
            cancel_event=self._cancel,
        )

        self._result.restored = apply_result.restored
        self._result.deleted_files = apply_result.deleted_files
        self._result.created_dirs = apply_result.created_dirs
        self._result.deleted_dirs = apply_result.deleted_dirs
        self._result.errors = apply_result.errors
        self._result.cancelled = apply_result.cancelled
        self._result.elapsed_sec = (
            time.perf_counter() - started
        )

        if self._result.cancelled:
            self._rollback()
            self._emit_done()
            return

        if self._result.errors == 0:
            self._save_current(
                self._target_name, last_action="restore",
                restored_from=self._target_name,
            )
            self._result.restored_from_state = self._target_name
        self._emit_done()

    # --- Загрузка target ---

    def _load_target(self) -> bool:
        assert self._state_store is not None
        try:
            self._target = self._state_store.load(
                self._backup_state_ref,
            )
            self._target_name = Path(
                self._backup_state_ref,
            ).name
        except StateStoreError as exc:
            self._emit_error(
                f"Не удалось загрузить состояние: {exc}"
            )
            return False

        if not self._target_name.endswith(".json"):
            self._target_name += ".json"
        return True

    @staticmethod
    def _should_skip(
        current: StateData, target: StateData | None,
    ) -> bool:
        if target is None:
            return False
        cur = {f.path: f.sha256 for f in current.files}
        tgt = {f.path: f.sha256 for f in target.files}
        if cur != tgt:
            return False
        return set(current.empty_dirs) == set(
            target.empty_dirs
        )

    # --- Restore point ---

    def _resolve_restore_point(
        self, current: StateData,
    ) -> None:
        """Определяет restore_point с дедупликацией.

        1. Если current.state совпадает с destination —
           переиспользуем его.
        2. Иначе ищем среди всех states совпадающий —
           переиспользуем.
        3. Иначе создаём новый restore_point.

        Это устраняет «плодятся точки возврата» при
        переключениях между резервными копиями без ручных
        правок.
        """
        assert self._state_store is not None
        assert self._current is not None

        # 1. current.state
        cur = self._current.load()
        if cur is not None and cur.state:
            try:
                existing = self._state_store.load(cur.state)
            except StateStoreError:
                existing = None
            if existing is not None and self._should_skip(
                current, existing,
            ):
                self._restore_point_name = cur.state
                self._result.restore_point_path = str(
                    self._state_store.root / cur.state,
                )
                self._result.reused_restore_point = True
                logger.info(
                    "Restore: destination совпадает с %s — "
                    "переиспользуем как точку возврата",
                    cur.state,
                )
                return

        # 2. Любой существующий state с тем же содержимым.
        existing_name = self._find_matching_state(current)
        if existing_name is not None:
            self._restore_point_name = existing_name
            self._result.restore_point_path = str(
                self._state_store.root / existing_name,
            )
            self._result.reused_restore_point = True
            logger.info(
                "Restore: destination совпадает с существующим "
                "%s — переиспользуем как точку возврата",
                existing_name,
            )
            return

        # 3. Создаём новый.
        current.kind = STATE_KIND_RESTORE_POINT
        current.source = (
            self._target.source if self._target else ""
        )
        try:
            path = self._state_store.create(current)
        except StateStoreError as exc:
            logger.error("restore_point: %r", exc)
            return
        self._restore_point_name = path.name
        self._result.restore_point_path = str(path)
        logger.info(
            "Создана точка возврата: %s", path.name,
        )

    def _find_matching_state(
        self, data: StateData,
    ) -> str | None:
        """Ищет существующий state с идентичным содержимым."""
        if self._state_store is None:
            return None

        data_files = {f.path: f.sha256 for f in data.files}
        data_empty = set(data.empty_dirs)
        n_files = len(data.files)
        n_empty = len(data.empty_dirs)

        try:
            infos = self._state_store.list()
        except Exception as exc:
            logger.debug(
                "_find_matching_state: list: %r", exc,
            )
            return None

        for info in infos:
            if info.files_count != n_files:
                continue
            if info.empty_dirs_count != n_empty:
                continue
            try:
                candidate = self._state_store.load(
                    info.path.name,
                )
            except Exception as exc:
                logger.debug(
                    "_find_matching_state: load %s: %r",
                    info.path.name, exc,
                )
                continue
            cand_files = {
                f.path: f.sha256 for f in candidate.files
            }
            if cand_files != data_files:
                continue
            if set(candidate.empty_dirs) != data_empty:
                continue
            return info.path.name
        return None

    # --- Откат ---

    def _rollback(self) -> None:
        if (
            self._restore_point_name is None
            or self._state_store is None
            or self._blobs is None
            or self._cache is None
        ):
            return

        try:
            target = self._state_store.load(
                self._restore_point_name,
            )
        except StateStoreError as exc:
            logger.error(
                "Rollback: не загрузить restore_point: %r",
                exc,
            )
            self._result.rollback_attempted = True
            self._result.rollback_errors = 1
            return

        current = scan_destination(
            self._destination, self._cache,
        )
        self._populate_blobs(current)

        plan = build_plan(target, current, self._blobs)
        apply_result = apply_plan(
            plan, target, self._destination,
            on_progress=None,
            cancel_event=None,
        )

        self._result.rollback_attempted = True
        self._result.rollback_errors = apply_result.errors
        self._result.rolled_back = apply_result.errors == 0

        if apply_result.errors == 0:
            self._save_current(
                self._restore_point_name,
                last_action="rollback",
                restored_from=self._restore_point_name,
            )
            logger.info("Откат restore успешен")

    # --- Вспомогательное ---

    def _populate_blobs(self, data: StateData) -> None:
        if self._blobs is None:
            return
        base = Path(self._destination)
        for f in data.files:
            full = base / f.path
            if not full.is_file():
                continue
            try:
                self._blobs.put(str(full), f.sha256)
            except Exception as exc:
                logger.warning("populate_blobs: %r", exc)

    def _save_current(
        self, state_name: str, *, last_action: str,
        restored_from: str,
    ) -> None:
        if self._current is None:
            return
        try:
            self._current.save(CurrentData(
                state=state_name,
                last_action=last_action,
                last_action_at="",
                restored_from=restored_from,
            ))
        except Exception as exc:
            logger.warning("save current: %r", exc)

    # --- События ---

    def _on_apply_progress(
        self, processed: int, total: int,
    ) -> None:
        self._emit_progress(processed, total)

    def _emit_progress(
        self, processed: int, total: int,
    ) -> None:
        progress = RestoreProgress(
            processed=processed, total=total,
        )
        is_final = processed >= total
        if (
            progress.percent == self._last_percent
            and not is_final
        ):
            return
        self._last_percent = progress.percent
        self._safe_schedule(
            lambda p=progress: self._on_progress(p),
            "on_progress",
        )

    def _emit_done(self) -> None:
        self._safe_schedule(
            lambda r=self._result: self._on_done(r),
            "on_done",
        )

    def _emit_error(self, message: str) -> None:
        self._safe_schedule(
            lambda m=message: self._on_error(m),
            "on_error",
        )

    def _safe_schedule(
        self, callback: Callable[[], None], name: str,
    ) -> None:
        try:
            self._schedule(callback)
        except Exception as exc:
            logger.error(
                "scheduler упал на %s: %r", name, exc,
            )


# --- Сервис ---

class RestoreService:
    """Управляет одним активным восстановлением."""

    def __init__(
        self,
        scheduler: Callable[[Callable[[], None]], None] | None = None,
    ):
        self._scheduler = scheduler or (lambda fn: fn())
        self._lock = threading.Lock()
        self._worker: _RestoreWorker | None = None
        self._cancel_event: threading.Event | None = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return (
                self._worker is not None
                and self._worker.is_alive()
            )

    def start(
        self,
        backup_state_ref: str,
        destination: str,
        on_progress: Callable[[RestoreProgress], None],
        on_done: Callable[[RestoreResult], None],
        on_error: Callable[[str], None],
    ) -> bool:
        with self._lock:
            if (
                self._worker is not None
                and self._worker.is_alive()
            ):
                logger.warning(
                    "Восстановление уже выполняется",
                )
                return False

            if not backup_state_ref or not destination:
                return self._fail(
                    on_error,
                    "Не указано состояние или папка назначения",
                )

            dst = Path(destination)
            if not dst.is_dir():
                return self._fail(
                    on_error,
                    "Папка назначения не найдена: "
                    f"{destination}",
                )

            self._cancel_event = threading.Event()
            self._worker = _RestoreWorker(
                backup_state_ref=backup_state_ref,
                destination=destination,
                cancel_event=self._cancel_event,
                scheduler=self._scheduler,
                on_progress=on_progress,
                on_done=on_done,
                on_error=on_error,
            )
            self._worker.start()
            logger.info(
                "Восстановление запущено: %s → %s",
                backup_state_ref, destination,
            )
            return True

    def cancel(self) -> None:
        with self._lock:
            if self._cancel_event is None:
                return
            self._cancel_event.set()
            logger.info(
                "Запрошена отмена восстановления",
            )

    def _fail(
        self,
        on_error: Callable[[str], None],
        message: str,
    ) -> bool:
        logger.warning(message)
        try:
            self._scheduler(lambda: on_error(message))
        except Exception as exc:
            logger.error(
                "scheduler упал на on_error: %r", exc,
            )
        return False
