"""Сервис копирования файлов.

Копирует содержимое source в destination. Если файл в destination
отличается от source — сохраняет старую версию в бэкап и
перезаписывает. Бэкап-папка создаётся один раз, только при первом
реальном различии.

Работает в отдельном потоке. Прогресс, завершение и ошибки
доставляются через callbacks, обёрнутые scheduler. По умолчанию
scheduler вызывает callback напрямую; из UI передаётся обёртка
вида self.after(0, fn) — тогда callbacks исполняются в UI-потоке.
"""

from __future__ import annotations

import filecmp
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)


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


# --- Исключения ---

class CopyError(RuntimeError):
    """Базовая ошибка копирования."""


class CopyValidationError(CopyError):
    """Параметры не прошли проверку."""


# --- Проверки ---

def _validate(source: str, destination: str) -> None:
    if not source:
        raise CopyValidationError("Не указана исходная директория")
    if not destination:
        raise CopyValidationError("Не указана целевая директория")

    src = Path(source).resolve()
    dst = Path(destination).resolve()

    if not src.is_dir():
        raise CopyValidationError(
            f"Исходная директория не найдена: {src}",
        )
    if not dst.is_dir():
        raise CopyValidationError(
            f"Целевая директория не найдена: {dst}",
        )

    if src == dst:
        raise CopyValidationError(
            "Исходная и целевая директории совпадают",
        )

    if src in dst.parents:
        raise CopyValidationError(
            "Целевая директория находится внутри исходной",
        )
    if dst in src.parents:
        raise CopyValidationError(
            "Исходная директория находится внутри целевой",
        )


# --- Воркер ---

class _CopyWorker(threading.Thread):
    def __init__(
        self,
        source: str,
        destination: str,
        create_backup: bool,
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
        self._backup_dir: Path | None = None

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

        if not files:
            self._result.elapsed_sec = time.perf_counter() - started
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
        self._emit_done()

    # --- Внутреннее ---

    def _collect_files(self) -> list[str]:
        """Относительные пути всех файлов из source."""
        result: list[str] = []
        for root, _dirs, names in os.walk(self._source):
            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, self._source)
                result.append(rel)
        return result

    def _process_file(self, rel_path: str) -> None:
        src_path = os.path.join(self._source, rel_path)
        dst_path = os.path.join(self._destination, rel_path)

        # Создаём директорию назначения (если файл в подпапке)
        dst_dir = os.path.dirname(dst_path)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)

        # Если в destination файла ещё нет — просто копируем
        if not os.path.isfile(dst_path):
            shutil.copy2(src_path, dst_path)
            self._result.copied += 1
            return

        # Сравниваем: одинаковые — пропускаем
        try:
            same = filecmp.cmp(src_path, dst_path, shallow=True)
        except Exception as exc:
            logger.debug(
                "filecmp.cmp упал для %s: %r", rel_path, exc,
            )
            same = False

        if same:
            self._result.skipped += 1
            return

        # Разные — бэкап старой версии (если нужно) и перезапись
        if self._create_backup:
            self._ensure_backup_dir()
            backup_path = os.path.join(
                str(self._backup_dir), rel_path,
            )
            backup_sub = os.path.dirname(backup_path)
            if backup_sub:
                os.makedirs(backup_sub, exist_ok=True)
            shutil.copy2(dst_path, backup_path)

        shutil.copy2(src_path, dst_path)
        self._result.copied += 1

    def _ensure_backup_dir(self) -> None:
        if self._backup_dir is not None:
            return

        stamp = datetime.now().strftime("%d.%m.%Y_%H.%M.%S_%f")[:-3]
        suffix = uuid.uuid4().hex[:6]
        name = f"!Backup_{stamp}_{suffix}"

        path = Path(self._destination) / name
        path.mkdir(parents=True, exist_ok=True)

        self._backup_dir = path
        self._result.backup_dir = str(path)
        logger.info("Создана папка бэкапа: %s", path)

    # --- Доставка событий ---

    def _emit_progress(self, processed: int) -> None:
        progress = CopyProgress(
            processed=processed,
            total=self._result.total,
            copied=self._result.copied,
            skipped=self._result.skipped,
        )
        # Прогресс шлём, только когда меняется целочисленный
        # процент — иначе UI получает сотни лишних обновлений.
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
        # scheduler — как доставить callback: напрямую или в UI-поток.
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
    ) -> bool:
        """Запускает копирование.

        Возвращает True, если поток стартовал. False — если уже идёт
        другое копирование или параметры не прошли валидацию (в
        последнем случае on_error уже вызван через scheduler).
        """
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
                cancel_event=self._cancel_event,
                scheduler=self._scheduler,
                on_progress=on_progress,
                on_done=on_done,
                on_error=on_error,
            )
            self._worker.start()
            logger.info(
                "Копирование запущено: %s → %s", source, destination,
            )
            return True

    def cancel(self) -> None:
        """Запрос отмены текущего копирования. Поток остановится на
        следующей итерации, результат придёт в on_done с
        cancelled=True."""
        with self._lock:
            if self._cancel_event is None:
                return
            self._cancel_event.set()
            logger.info("Запрошена отмена копирования")
