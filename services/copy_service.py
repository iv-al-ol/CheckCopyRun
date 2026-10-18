"""Сервис копирования файлов с безопасным бэкапом и откатом.

Копирует содержимое source в destination. Если файл в destination
отличается от source — сохраняет старую версию в бэкап и
перезаписывает. Бэкапятся строго те файлы, которые заменяются.

Сравнение с кэшем SHA-256: файлы проверяются по размеру и mtime,
хэш пересчитывается только при изменениях. Кэш живёт в
<destination>/!CCRun/hashes.json.

Безопасная отмена: destination возвращается к состоянию
«до копирования» — заменённые восстанавливаются из бэкапа,
созданные нами удаляются.

Проверка конфликта путей — core.paths.path_conflict_error.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.paths import path_conflict_error
from services.copy_backup import BackupManager
from services.copy_constants import is_special_first_segment
from services.copy_errors import (
    BackupVerificationError,
    CopyError,
    CopyValidationError,
)
from services.copy_manifest import write_manifest
from services.copy_rollback import RollbackManager
from services.file_compare import (
    ComparisonResult,
    files_identical,
)
from services.hash_cache import HashCache, hash_file
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = [
    "BackupVerificationError",
    "CopyError",
    "CopyProgress",
    "CopyResult",
    "CopyService",
    "CopyValidationError",
    "format_cancel_status",
]


# --- Результаты ---

@dataclass
class CopyProgress:
    processed: int
    total: int
    copied: int
    skipped: int

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 100
        return int(self.processed * 100 / self.total)


@dataclass
class CopyResult:
    total: int = 0
    copied: int = 0
    skipped: int = 0
    errors: int = 0
    backup_dir: str | None = None
    cancelled: bool = False
    elapsed_sec: float = 0.0

    rollback_attempted: bool = False
    rolled_back: bool = False
    rollback_restored: int = 0
    rollback_deleted: int = 0
    rollback_errors: int = 0


def format_cancel_status(result: CopyResult) -> str:
    if not result.rollback_attempted:
        return "Копирование отменено"

    if not result.rolled_back:
        return (
            f"Копирование отменено, откат неполный "
            f"({result.rollback_errors} ошибок) — см. лог"
        )

    if result.rollback_restored > 0 or result.rollback_deleted > 0:
        return (
            "Копирование отменено, "
            "замененные файлы восстановлены обратно"
        )

    return "Копирование отменено, изменений не было"


# --- Проверки ---

def _validate(source: str, destination: str) -> None:
    """Проверка путей перед копированием.

    Использует path_conflict_error из core.paths — единый
    источник правил «что считается конфликтом» для сервиса и
    UI-слоя.
    """
    if not source:
        raise CopyValidationError("Не указана исходная директория")
    if not destination:
        raise CopyValidationError("Не указана целевая директория")

    if not Path(source).is_dir():
        raise CopyValidationError(
            f"Исходная директория не найдена: {source}",
        )
    if not Path(destination).is_dir():
        raise CopyValidationError(
            f"Целевая директория не найдена: {destination}",
        )

    conflict = path_conflict_error(source, destination)
    if conflict:
        raise CopyValidationError(conflict)


# --- Воркер ---

class _CopyWorker(threading.Thread):
    def __init__(
        self,
        source: str,
        destination: str,
        create_backup: bool,
        hash_cache_enabled: bool,
        cancel_event: threading.Event,
        scheduler: Callable[[Callable[[], None]], None],
        on_progress: Callable[[CopyProgress], None],
        on_done: Callable[[CopyResult], None],
        on_error: Callable[[str], None],
    ):
        super().__init__(name="CopyWorker", daemon=True)
        self._source = source
        self._destination = destination
        self._create_backup = create_backup
        self._cancel = cancel_event
        self._schedule = scheduler
        self._on_progress = on_progress
        self._on_done = on_done
        self._on_error = on_error

        self._result = CopyResult()
        self._last_percent = -1

        self._backup: BackupManager | None = None
        self._cache = HashCache(
            destination, enabled=hash_cache_enabled,
        )

        self._replaced_without_backup: list[str] = []
        self._created_files: list[str] = []
        self._created_dirs: set[str] = set()

    # --- Публичное ---

    def run(self) -> None:
        started = time.perf_counter()

        try:
            files = self._collect_files()
        except Exception as exc:
            logger.exception("Ошибка сбора файлов")
            self._emit_error(
                f"Ошибка чтения исходной директории: {exc}",
            )
            return

        self._result.total = len(files)
        self._emit_progress(0)

        self._cache.load()

        if not files:
            self._result.elapsed_sec = time.perf_counter() - started
            self._prune_cache(set())
            self._cache.save()
            self._emit_done()
            return

        processed = 0
        for rel_path in files:
            if self._cancel.is_set():
                self._result.cancelled = True
                break
            try:
                self._process_file(rel_path)
            except Exception as exc:
                logger.error(
                    "Ошибка обработки %s: %r", rel_path, exc,
                )
                self._result.errors += 1
            processed += 1
            self._emit_progress(processed)

        self._result.elapsed_sec = time.perf_counter() - started

        if self._result.cancelled:
            self._rollback()
            self._invalidate_cache_after_rollback()

        self._prune_cache(set(files))
        self._cache.save()

        self._write_manifest()
        self._emit_done()

    # --- Сбор файлов ---

    def _collect_files(self) -> list[str]:
        result: list[str] = []

        for root, dirs, names in os.walk(self._source):
            rel_root = os.path.relpath(root, self._source)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]

            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, self._source)

                first = rel.split(os.sep, 1)[0]
                if is_special_first_segment(first):
                    continue

                result.append(rel)

        return result

    # --- Обработка одного файла ---

    def _process_file(self, rel_path: str) -> None:
        src_path = os.path.join(self._source, rel_path)
        dst_path = os.path.join(self._destination, rel_path)

        dst_dir = os.path.dirname(dst_path)
        if dst_dir:
            self._ensure_dst_dir_tracked(dst_dir)

        # 1. Новый файл — копируем и сразу кэшируем.
        if not os.path.isfile(dst_path):
            shutil.copy2(src_path, dst_path)
            self._result.copied += 1
            self._created_files.append(rel_path)
            self._cache_new_file(rel_path, src_path)
            return

        # 2. Сравниваем с учётом кэша.
        outcome = files_identical(
            src_path, dst_path, rel_path, self._cache,
        )

        if outcome.result == ComparisonResult.SAME:
            self._result.skipped += 1
            return

        # 3. Отличается — бэкап (если нужно) и перезапись.
        if self._create_backup:
            self._ensure_backup_manager()
            assert self._backup is not None
            self._backup.backup(rel_path, dst_path)
        else:
            self._replaced_without_backup.append(rel_path)

        shutil.copy2(src_path, dst_path)
        self._result.copied += 1

        # 4. Обновляем кэш после замены.
        if self._cache.enabled:
            if outcome.src_hash is not None:
                self._cache.put(
                    rel_path,
                    size=outcome.src_size,
                    src_mtime_ns=outcome.src_mtime_ns,
                    dst_mtime_ns=outcome.src_mtime_ns,
                    sha256=outcome.src_hash,
                )
            else:
                # size-differ case — src_hash не был вычислен.
                self._cache_new_file(rel_path, src_path)

    def _cache_new_file(self, rel_path: str, src_path: str) -> None:
        if not self._cache.enabled:
            return
        try:
            src_stat = os.stat(src_path)
            src_hash = hash_file(src_path, self._cache.algorithm)
        except OSError as exc:
            logger.debug(
                "не удалось захэшировать %s: %r", src_path, exc,
            )
            return

        self._cache.put(
            rel_path,
            size=src_stat.st_size,
            src_mtime_ns=src_stat.st_mtime_ns,
            dst_mtime_ns=src_stat.st_mtime_ns,
            sha256=src_hash,
        )

    def _prune_cache(self, current_files: set[str]) -> None:
        if not self._cache.enabled:
            return
        for rel in self._cache.paths():
            if rel not in current_files:
                self._cache.remove(rel)

    # --- Директории ---

    def _ensure_dst_dir_tracked(self, dst_dir: str) -> None:
        if not dst_dir or os.path.isdir(dst_dir):
            return

        to_create: list[str] = []
        current = dst_dir
        while current and current != os.path.dirname(current):
            if os.path.isdir(current):
                break
            to_create.append(current)
            current = os.path.dirname(current)

        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as exc:
            logger.error(
                "Не удалось создать %s: %r", dst_dir, exc,
            )
            raise

        self._created_dirs.update(to_create)

    # --- Бэкап ---

    def _ensure_backup_manager(self) -> None:
        if self._backup is not None:
            return
        self._backup = BackupManager(self._destination)
        self._backup.ensure_dir()
        self._result.backup_dir = str(self._backup.backup_dir)

    # --- Откат ---

    def _rollback(self) -> None:
        replaced_entries = (
            list(self._backup.entries) if self._backup else []
        )
        backup_dir = (
            self._backup.backup_dir if self._backup else None
        )

        manager = RollbackManager(
            destination=self._destination,
            backup_dir=backup_dir,
        )
        result = manager.rollback(
            replaced_entries=replaced_entries,
            replaced_without_backup=self._replaced_without_backup,
            created_files=self._created_files,
            created_dirs=self._created_dirs,
        )

        self._result.rollback_attempted = result.attempted
        self._result.rollback_restored = result.restored
        self._result.rollback_deleted = result.deleted
        self._result.rollback_errors = result.errors
        self._result.rolled_back = result.succeeded

    def _invalidate_cache_after_rollback(self) -> None:
        if not self._cache.enabled:
            return
        for rel in self._created_files:
            self._cache.remove(rel)
        if self._backup is not None:
            for entry in self._backup.entries:
                self._cache.remove(entry.path)

    # --- Манифест ---

    def _write_manifest(self) -> None:
        if self._backup is None or self._backup.backup_dir is None:
            return

        entries = list(self._backup.entries)
        summary: dict = {
            "backed_up": len(entries),
            "copied": self._result.copied,
            "skipped": self._result.skipped,
            "errors": self._result.errors,
            "cancelled": self._result.cancelled,
            "elapsed_sec": round(self._result.elapsed_sec, 3),
        }

        if self._result.cancelled:
            summary["rollback"] = {
                "attempted": self._result.rollback_attempted,
                "succeeded": self._result.rolled_back,
                "restored": self._result.rollback_restored,
                "deleted": self._result.rollback_deleted,
                "errors": self._result.rollback_errors,
            }

        write_manifest(
            self._backup.backup_dir,
            source=self._source,
            destination=self._destination,
            files=entries,
            summary=summary,
        )

    # --- Доставка событий ---

    def _emit_progress(self, processed: int) -> None:
        progress = CopyProgress(
            processed=processed,
            total=self._result.total,
            copied=self._result.copied,
            skipped=self._result.skipped,
        )
        is_final = processed == self._result.total
        if progress.percent == self._last_percent and not is_final:
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
            logger.error("scheduler упал на %s: %r", name, exc)


# --- Сервис ---

class CopyService:
    """Управляет одним активным копированием."""

    def __init__(
        self,
        scheduler: Callable[[Callable[[], None]], None] | None = None,
    ):
        self._scheduler = scheduler or (lambda fn: fn())
        self._lock = threading.Lock()
        self._worker: _CopyWorker | None = None
        self._cancel_event: threading.Event | None = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def start(
        self,
        source: str,
        destination: str,
        create_backup: bool,
        on_progress: Callable[[CopyProgress], None],
        on_done: Callable[[CopyResult], None],
        on_error: Callable[[str], None],
        *,
        hash_cache_enabled: bool = True,
    ) -> bool:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                logger.warning("Копирование уже выполняется")
                return False

            try:
                _validate(source, destination)
            except CopyValidationError as exc:
                logger.warning("Копирование не запущено: %s", exc)
                try:
                    self._scheduler(lambda: on_error(str(exc)))
                except Exception as sched_exc:
                    logger.error(
                        "scheduler упал на on_error: %r", sched_exc,
                    )
                return False

            self._cancel_event = threading.Event()
            self._worker = _CopyWorker(
                source=source,
                destination=destination,
                create_backup=create_backup,
                hash_cache_enabled=hash_cache_enabled,
                cancel_event=self._cancel_event,
                scheduler=self._scheduler,
                on_progress=on_progress,
                on_done=on_done,
                on_error=on_error,
            )
            self._worker.start()
            logger.info(
                "Копирование запущено: %s → %s (cache=%s)",
                source, destination, hash_cache_enabled,
            )
            return True

    def cancel(self) -> None:
        with self._lock:
            if self._cancel_event is None:
                return
            self._cancel_event.set()
            logger.info(
                "Запрошена отмена копирования — будет выполнен откат",
            )
