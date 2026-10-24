"""Сервис копирования файлов с CAS-состояниями, mirror и
автооткатом при отмене.

Фазы прогресса:
  • "copy"         — копирование файлов;
  • "save_scan"    — сканирование destination (stat+hash);
  • "save_store"   — сохранение новых blob-ов в хранилище.

Дедупликация состояний:
  • перед созданием state_before/state_after ищем среди
    существующих state-файлов такой, чьё содержимое совпадает
    с текущим data. Если нашли — переиспользуем (не создаём
    новый файл);
  • restore_point исключён из поиска (у него отдельная
    семантика в UI);
  • если состояние совпадает с current.state — вообще ничего
    не делаем.

Это устраняет разрастание списка резервных копий: при copy
без изменений, при copy после restore, при повторных
состояниях новых файлов не появляется.
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
from services.blob_store import BlobStore
from services.copy_constants import (
    STATE_KIND_AUTO,
    STATE_KIND_RESTORE_POINT,
    STATE_VERSION,
    is_special_first_segment,
)
from services.copy_errors import (
    CopyError,
    CopyValidationError,
)
from services.current_pointer import (
    CurrentData,
    CurrentPointer,
)
from services.file_compare import (
    ComparisonResult,
    files_identical,
)
from services.hash_cache import HashCache, hash_file
from services.mirror_check import is_reparse_point
from services.restore_apply import apply_plan
from services.restore_planner import build_plan
from services.state_scanner import (
    list_user_files,
    scan_destination,
)
from services.state_store import (
    StateData,
    StateFile,
    StateStore,
    StateStoreError,
    now_iso,
)
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = [
    "PHASE_COPY",
    "PHASE_SAVE_SCAN",
    "PHASE_SAVE_STORE",
    "CopyError",
    "CopyProgress",
    "CopyResult",
    "CopyService",
    "CopyValidationError",
    "format_cancel_status",
    "format_copy_status",
]


# --- Фазы ---

PHASE_COPY = "copy"
PHASE_SAVE_SCAN = "save_scan"
PHASE_SAVE_STORE = "save_store"


# --- Результаты ---

@dataclass
class CopyProgress:
    processed: int
    total: int
    copied: int
    skipped: int
    phase: str = PHASE_COPY

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

    state_before_path: str | None = None
    state_after_path: str | None = None

    cancelled: bool = False
    elapsed_sec: float = 0.0

    rollback_attempted: bool = False
    rolled_back: bool = False
    rollback_restored: int = 0
    rollback_deleted: int = 0
    rollback_errors: int = 0

    mirror_removed_files: int = 0
    mirror_removed_dirs: int = 0


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


def format_copy_status(result: CopyResult) -> str:
    """Текст для статус-бара после завершения копирования."""
    if result.cancelled:
        return format_cancel_status(result)

    if result.errors:
        parts = [
            f"скопировано {result.copied}",
            f"пропущено {result.skipped}",
            f"ошибок {result.errors}",
        ]
        return "Копирование завершено: " + ", ".join(parts)

    mirror_changed = (
        result.mirror_removed_files > 0
        or result.mirror_removed_dirs > 0
    )

    if result.copied == 0 and not mirror_changed:
        if result.skipped == 0:
            return "Копирование завершено: файлов в источнике нет"
        return (
            f"Копирование завершено: изменений нет — "
            f"все {result.skipped} "
            f"{_plural_files(result.skipped)} уже актуальны"
        )

    parts = [
        f"скопировано {result.copied}",
        f"пропущено {result.skipped}",
    ]
    if result.state_after_path:
        parts.append(
            f"состояние: {Path(result.state_after_path).stem}"
        )
    return "Копирование завершено: " + ", ".join(parts)


def _plural_files(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "файл"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "файла"
    return "файлов"


# --- Проверки ---

def _validate(source: str, destination: str) -> None:
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
        mirror_mode: bool,
        cancel_event: threading.Event,
        scheduler: Callable[[Callable[[], None]], None],
        on_progress: Callable[[CopyProgress], None],
        on_done: Callable[[CopyResult], None],
        on_error: Callable[[str], None],
    ):
        super().__init__(name="CopyWorker", daemon=True)
        self._source = source
        self._destination = destination
        self._create_state = create_backup
        self._mirror_mode = mirror_mode
        self._cancel = cancel_event
        self._schedule = scheduler
        self._on_progress = on_progress
        self._on_done = on_done
        self._on_error = on_error

        self._result = CopyResult()
        self._last_percent = -1
        self._last_save_percent = -1
        self._last_save_phase = ""
        self._changed = False

        self._cache = HashCache(
            destination, enabled=hash_cache_enabled,
        )

        self._state_store: StateStore | None = None
        self._blobs: BlobStore | None = None
        self._current: CurrentPointer | None = None

        self._mirror_removed_files: list[str] = []
        self._mirror_removed_dirs: list[str] = []

    # --- Публичное ---

    def run(self) -> None:
        started = time.perf_counter()

        create_state = (
            self._create_state or self._mirror_mode
        )

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

        if create_state:
            try:
                self._state_store = StateStore(
                    self._destination,
                )
                self._blobs = BlobStore(self._destination)
                self._current = CurrentPointer(
                    self._destination,
                )
            except Exception as exc:
                logger.exception(
                    "Не удалось инициализировать хранилище",
                )
                self._emit_error(
                    f"Ошибка инициализации хранилища: {exc}"
                )
                return

            self._ensure_state_before()

        processed = 0
        for rel_path in files:
            if self._cancel.is_set():
                self._result.cancelled = True
                break
            try:
                if self._process_file(rel_path):
                    self._changed = True
            except Exception as exc:
                logger.error(
                    "Ошибка обработки %s: %r",
                    rel_path, exc,
                )
                self._result.errors += 1
            processed += 1
            self._emit_progress(processed)

        if self._mirror_mode and not self._result.cancelled:
            try:
                if self._apply_mirror():
                    self._changed = True
            except Exception as exc:
                logger.error("Ошибка mirror: %r", exc)
                self._result.errors += 1

        self._result.elapsed_sec = (
            time.perf_counter() - started
        )

        if self._result.cancelled:
            if create_state:
                self._perform_rollback()
            self._emit_done()
            return

        if create_state:
            self._ensure_state_after()

        self._prune_cache(set(files))
        self._cache.save()
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

    # --- Обработка файла ---

    def _process_file(self, rel_path: str) -> bool:
        src_path = os.path.join(self._source, rel_path)
        dst_path = os.path.join(self._destination, rel_path)

        dst_dir = os.path.dirname(dst_path)
        if dst_dir:
            self._ensure_dst_dir(dst_dir)

        if not os.path.isfile(dst_path):
            shutil.copy2(src_path, dst_path)
            self._result.copied += 1
            self._cache_new_file(rel_path, src_path)
            return True

        outcome = files_identical(
            src_path, dst_path, rel_path, self._cache,
        )
        if outcome.result == ComparisonResult.SAME:
            self._result.skipped += 1
            return False

        shutil.copy2(src_path, dst_path)
        self._result.copied += 1

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
                self._cache_new_file(rel_path, src_path)
        return True

    def _cache_new_file(
        self, rel_path: str, src_path: str,
    ) -> None:
        if not self._cache.enabled:
            return
        try:
            st = os.stat(src_path)
            sha = hash_file(src_path, self._cache.algorithm)
        except OSError as exc:
            logger.debug(
                "cache_new_file %s: %r", src_path, exc,
            )
            return
        self._cache.put(
            rel_path,
            size=st.st_size,
            src_mtime_ns=st.st_mtime_ns,
            dst_mtime_ns=st.st_mtime_ns,
            sha256=sha,
        )

    def _prune_cache(self, current_files: set[str]) -> None:
        if not self._cache.enabled:
            return
        for rel in self._cache.paths():
            if rel not in current_files:
                self._cache.remove(rel)

    @staticmethod
    def _ensure_dst_dir(dst_dir: str) -> None:
        if not dst_dir or os.path.isdir(dst_dir):
            return
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as exc:
            logger.error(
                "Не удалось создать %s: %r", dst_dir, exc,
            )
            raise

    # --- CAS: состояния ---

    def _ensure_state_before(self) -> None:
        assert self._state_store is not None
        assert self._blobs is not None
        assert self._current is not None

        try:
            file_list = list_user_files(self._destination)
        except Exception as exc:
            logger.warning(
                "list_user_files (before): %r", exc,
            )
            return

        data = self._scan_with_progress(
            file_list, kind_state="before",
        )
        if data is None:
            return

        current_data = self._load_current_state()

        # Пустой destination + нет current — нечего откатывать.
        if (
            current_data is None
            and not data.files
            and not data.empty_dirs
        ):
            logger.debug(
                "Destination пуст и current не задан — "
                "state_before не нужен",
            )
            return

        if self._states_equal(data, current_data):
            logger.debug(
                "Состояние совпадает с current — "
                "state_before не нужен",
            )
            return

        self._populate_for_data(data)

        name, created = self._find_or_create_state(
            data, kind_state="before",
        )
        if not name:
            return

        self._result.state_before_path = str(
            self._state_store.root / name,
        )
        if not created:
            logger.info(
                "state_before переиспользует существующий: %s",
                name,
            )

    def _ensure_state_after(self) -> None:
        assert self._state_store is not None
        assert self._blobs is not None
        assert self._current is not None

        if not self._changed:
            # Изменений нет. Если был определён state_before
            # (создан или переиспользован), зафиксируем его в
            # current — это устраняет «current указывает не
            # туда», если пользователь пришёл из restore или
            # ручного откката.
            if self._result.state_before_path:
                name = Path(
                    self._result.state_before_path,
                ).name
                cur = self._current.load()
                if cur is None or cur.state != name:
                    self._current.save_copy(name)
                    logger.info(
                        "Изменений нет — current → %s",
                        name,
                    )
            return

        try:
            file_list = list_user_files(self._destination)
        except Exception as exc:
            logger.warning(
                "list_user_files (after): %r", exc,
            )
            return

        data = self._scan_with_progress(
            file_list, kind_state="after",
        )
        if data is None:
            return

        self._populate_for_data(data)

        name, created = self._find_or_create_state(
            data, kind_state="after",
        )
        if not name:
            return

        self._result.state_after_path = str(
            self._state_store.root / name,
        )
        if not created:
            logger.info(
                "state_after переиспользует существующий: %s",
                name,
            )
        self._current.save_copy(name)

    def _scan_with_progress(
        self,
        file_list: list[str],
        *,
        kind_state: str,
    ) -> StateData | None:
        n = len(file_list)
        self._last_save_percent = -1
        self._last_save_phase = ""

        if n > 0:
            self._emit_save_progress(0, n, PHASE_SAVE_SCAN)

        def on_scan(i: int, _t: int) -> None:
            self._emit_save_progress(i, n, PHASE_SAVE_SCAN)

        try:
            return scan_destination(
                self._destination,
                self._cache,
                file_list=file_list,
                on_progress=on_scan if n > 0 else None,
            )
        except Exception as exc:
            logger.warning(
                "scan_destination (%s): %r",
                kind_state, exc,
            )
            return None

    def _populate_for_data(self, data: StateData) -> None:
        """Сохранение новых blob-ов с прогрессом."""
        if self._blobs is None:
            return
        new_files = self._find_new_blobs(data)
        m = len(new_files)

        if m > 0:
            self._emit_save_progress(0, m, PHASE_SAVE_STORE)

            def on_store(i: int, _t: int) -> None:
                self._emit_save_progress(i, m, PHASE_SAVE_STORE)

            self._populate_blobs(
                data, new_files, on_progress=on_store,
            )
        else:
            data.summary["new_blobs_count"] = 0
            data.summary["new_blobs_bytes"] = 0
            logger.debug(
                "populate: все blob-ы уже в хранилище",
            )

    def _find_or_create_state(
        self, data: StateData, *, kind_state: str,
    ) -> tuple[str, bool]:
        """Переиспользует существующий state с таким же
        содержимым или создаёт новый.

        Возвращает (name, created):
          • created=True — создан новый state-файл;
          • created=False — переиспользован существующий;
          • ("", False) — не удалось создать.
        """
        assert self._state_store is not None

        existing = self._find_matching_state(
            data, exclude_kinds={STATE_KIND_RESTORE_POINT},
        )
        if existing is not None:
            return existing, False

        data.kind = STATE_KIND_AUTO
        data.source = self._source

        try:
            path = self._state_store.create(data)
        except StateStoreError as exc:
            logger.error(
                "Не удалось создать state_%s: %r",
                kind_state, exc,
            )
            return "", False

        logger.info(
            "Создан state_%s: %s", kind_state, path.name,
        )
        return path.name, True

    def _find_matching_state(
        self,
        data: StateData,
        *,
        exclude_kinds: set[str] | None = None,
    ) -> str | None:
        """Ищет существующий state, чьё содержимое совпадает с data.

        Быстрая проверка по summary (files_count и
        empty_dirs_count), затем полная — по {path: sha256} и
        empty_dirs.

        exclude_kinds — какие kind пропускать (например,
        restore_point в copy).
        """
        if self._state_store is None:
            return None

        skip_kinds = exclude_kinds or set()
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
            # Быстрая отбраковка без загрузки.
            if info.files_count != n_files:
                continue
            if info.empty_dirs_count != n_empty:
                continue
            if skip_kinds and info.kind in skip_kinds:
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

    def _load_current_state(self) -> StateData | None:
        assert self._current is not None
        assert self._state_store is not None
        cur = self._current.load()
        if cur is None or not cur.state:
            return None
        try:
            return self._state_store.load(cur.state)
        except StateStoreError as exc:
            logger.debug(
                "read current state %r: %r",
                cur.state, exc,
            )
            return None

    @staticmethod
    def _states_equal(
        a: StateData, b: StateData | None,
    ) -> bool:
        if b is None:
            return False
        a_files = {f.path: f.sha256 for f in a.files}
        b_files = {f.path: f.sha256 for f in b.files}
        if a_files != b_files:
            return False
        return set(a.empty_dirs) == set(b.empty_dirs)

    def _find_new_blobs(
        self, data: StateData,
    ) -> list[StateFile]:
        if self._blobs is None:
            return []
        result: list[StateFile] = []
        for f in data.files:
            if not self._blobs.has(f.sha256):
                result.append(f)
        return result

    def _populate_blobs(
        self,
        data: StateData,
        files_to_add: list[StateFile],
        *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        if self._blobs is None:
            return
        base = Path(self._destination)
        total = len(files_to_add)
        new_count = 0
        new_bytes = 0

        for idx, f in enumerate(files_to_add, 1):
            full = base / f.path
            if full.is_file():
                try:
                    is_new = self._blobs.put(
                        str(full), f.sha256,
                    )
                except Exception as exc:
                    logger.warning(
                        "populate_blobs: %r", exc,
                    )
                    is_new = False
                if is_new:
                    new_count += 1
                    new_bytes += f.size

            if on_progress is not None:
                try:
                    on_progress(idx, total)
                except Exception as exc:
                    logger.debug(
                        "populate on_progress: %r", exc,
                    )

        data.summary["new_blobs_count"] = new_count
        data.summary["new_blobs_bytes"] = new_bytes

    # --- Mirror ---

    def _apply_mirror(self) -> bool:
        extra_files, extra_dirs = (
            self._scan_destination_diff()
        )
        if not extra_files and not extra_dirs:
            return False

        logger.info(
            "Режим зеркала: к удалению %d файлов и %d "
            "директорий",
            len(extra_files), len(extra_dirs),
        )

        changed = False
        for rel in extra_files:
            dst = os.path.join(self._destination, rel)
            try:
                os.remove(dst)
                self._mirror_removed_files.append(rel)
                self._result.mirror_removed_files += 1
                changed = True
                if self._cache.enabled:
                    self._cache.remove(rel)
            except Exception as exc:
                logger.warning(
                    "mirror: не удалить файл %s: %r",
                    rel, exc,
                )

        extra_dirs.sort(
            key=lambda p: p.count(os.sep),
            reverse=True,
        )
        for rel in extra_dirs:
            dst = os.path.join(self._destination, rel)
            try:
                if not os.path.isdir(dst):
                    continue
                if os.listdir(dst):
                    continue
                os.rmdir(dst)
                self._mirror_removed_dirs.append(rel)
                self._result.mirror_removed_dirs += 1
                changed = True
            except Exception as exc:
                logger.warning(
                    "mirror: не удалить директорию %s: %r",
                    rel, exc,
                )
        return changed

    def _scan_destination_diff(
        self,
    ) -> tuple[list[str], list[str]]:
        extra_files: list[str] = []
        extra_dirs: list[str] = []
        for root, dirs, names in os.walk(self._destination):
            rel_root = os.path.relpath(root, self._destination)
            filtered: list[str] = []
            for d in dirs:
                full = os.path.join(root, d)
                if is_reparse_point(full):
                    continue
                if rel_root == "." and is_special_first_segment(d):
                    continue
                filtered.append(d)
            dirs[:] = filtered
            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, self._destination)
                if rel_root == "." and is_special_first_segment(
                    rel.split(os.sep, 1)[0]
                ):
                    continue
                src_path = os.path.join(self._source, rel)
                if not os.path.isfile(src_path):
                    extra_files.append(rel)
            for d in dirs:
                full = os.path.join(root, d)
                rel = os.path.relpath(full, self._destination)
                src_path = os.path.join(self._source, rel)
                if not os.path.isdir(src_path):
                    extra_dirs.append(rel)
        return extra_files, extra_dirs

    # --- Автооткат ---

    def _perform_rollback(self) -> None:
        if (
            self._state_store is None
            or self._blobs is None
            or self._current is None
        ):
            return

        target = self._get_rollback_target()
        if target is None:
            target = _empty_state()

        try:
            current = scan_destination(
                self._destination, self._cache,
            )
        except Exception as exc:
            logger.warning(
                "rollback scan_destination: %r", exc,
            )
            self._result.rollback_attempted = True
            self._result.rollback_errors = 1
            return

        self._populate_blobs(current, current.files)

        try:
            plan = build_plan(target, current, self._blobs)
        except Exception as exc:
            logger.error("rollback build_plan: %r", exc)
            self._result.rollback_attempted = True
            self._result.rollback_errors = 1
            return

        try:
            apply_result = apply_plan(
                plan, target, self._destination,
                on_progress=None,
                cancel_event=None,
            )
        except Exception as exc:
            logger.error("rollback apply_plan: %r", exc)
            self._result.rollback_attempted = True
            self._result.rollback_errors = 1
            return

        self._result.rollback_attempted = True
        self._result.rollback_restored = apply_result.restored
        self._result.rollback_deleted = (
            apply_result.deleted_files
            + apply_result.deleted_dirs
        )
        self._result.rollback_errors = apply_result.errors
        self._result.rolled_back = apply_result.errors == 0

        if apply_result.errors == 0:
            try:
                if self._result.state_before_path:
                    name = Path(
                        self._result.state_before_path,
                    ).name
                    self._current.save_restore(
                        name, restored_from=name,
                    )
                else:
                    self._current.save(CurrentData(
                        state="",
                        last_action="rollback",
                        last_action_at="",
                        restored_from="",
                    ))
            except Exception as exc:
                logger.warning(
                    "rollback: update current: %r", exc,
                )
            logger.info(
                "Откат copy успешен (восстановлено %d, "
                "удалено %d)",
                apply_result.restored,
                self._result.rollback_deleted,
            )
        else:
            logger.warning(
                "Откат copy неполный: %d ошибок",
                apply_result.errors,
            )

    def _get_rollback_target(self) -> StateData | None:
        assert self._state_store is not None
        assert self._current is not None

        if self._result.state_before_path:
            try:
                return self._state_store.load(
                    Path(
                        self._result.state_before_path,
                    ).name,
                )
            except StateStoreError as exc:
                logger.debug(
                    "rollback: не загрузить state_before: %r",
                    exc,
                )
                return None

        cur = self._current.load()
        if cur is not None and cur.state:
            try:
                return self._state_store.load(cur.state)
            except StateStoreError as exc:
                logger.debug(
                    "rollback: не загрузить current: %r", exc,
                )
                return None
        return None

    # --- Доставка событий ---

    def _emit_progress(self, processed: int) -> None:
        progress = CopyProgress(
            processed=processed,
            total=self._result.total,
            copied=self._result.copied,
            skipped=self._result.skipped,
            phase=PHASE_COPY,
        )
        is_final = processed == self._result.total
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

    def _emit_save_progress(
        self, processed: int, total: int, phase: str,
    ) -> None:
        progress = CopyProgress(
            processed=processed,
            total=total,
            copied=self._result.copied,
            skipped=self._result.skipped,
            phase=phase,
        )
        is_final = processed >= total
        same_phase = phase == self._last_save_phase
        if (
            same_phase
            and progress.percent == self._last_save_percent
            and not is_final
        ):
            return
        self._last_save_phase = phase
        self._last_save_percent = progress.percent
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


# --- Пустое состояние ---

def _empty_state() -> StateData:
    return StateData(
        version=STATE_VERSION,
        created_at=now_iso(),
        kind="",
        source="",
        files=[],
        empty_dirs=[],
        summary={
            "files_count": 0,
            "empty_dirs_count": 0,
            "total_size": 0,
            "new_blobs_count": 0,
            "new_blobs_bytes": 0,
        },
    )


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
            return (
                self._worker is not None
                and self._worker.is_alive()
            )

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
        mirror_mode: bool = False,
    ) -> bool:
        with self._lock:
            if (
                self._worker is not None
                and self._worker.is_alive()
            ):
                logger.warning("Копирование уже выполняется")
                return False

            try:
                _validate(source, destination)
            except CopyValidationError as exc:
                logger.warning(
                    "Копирование не запущено: %s", exc,
                )
                try:
                    self._scheduler(lambda: on_error(str(exc)))
                except Exception as sched_exc:
                    logger.error(
                        "scheduler упал на on_error: %r",
                        sched_exc,
                    )
                return False

            self._cancel_event = threading.Event()
            self._worker = _CopyWorker(
                source=source,
                destination=destination,
                create_backup=create_backup,
                hash_cache_enabled=hash_cache_enabled,
                mirror_mode=mirror_mode,
                cancel_event=self._cancel_event,
                scheduler=self._scheduler,
                on_progress=on_progress,
                on_done=on_done,
                on_error=on_error,
            )
            self._worker.start()
            logger.info(
                "Копирование запущено: %s → %s "
                "(create_state=%s, mirror=%s, cache=%s)",
                source, destination,
                create_backup or mirror_mode,
                mirror_mode, hash_cache_enabled,
            )
            return True

    def cancel(self) -> None:
        with self._lock:
            if self._cancel_event is None:
                return
            self._cancel_event.set()
            logger.info(
                "Запрошена отмена копирования — будет откат",
            )
