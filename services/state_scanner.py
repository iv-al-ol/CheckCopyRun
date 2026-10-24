"""Сканирование destination → StateData.

Обходит папку назначения и собирает полное состояние: список
файлов с sha256, список пустых директорий, агрегаты для UI.

Пропускаются:
  • служебная папка !CCRun;
  • старые папки !Backup_* (формат до CAS);
  • reparse points (symlinks, junctions) — не спускаемся внутрь.

Хэши берутся из HashCache, если запись актуальна (size + mtime_ns
совпадают). Иначе файл читается и хэшируется заново.

Прогресс:
  • list_user_files() — быстрый обход, только сбор путей;
  • scan_destination(file_list=..., on_progress=...) —
    итерация по готовому списку с отчётом о каждом файле.

Возвращаемый StateData содержит kind="" и source="" — их
заполняет вызывающий код (copy/restore). summary уже заполнен:
files_count, empty_dirs_count, total_size. Поля new_blobs_count /
new_blobs_bytes равны 0 — их выставляет вызывающий после
пополнения blob-пула.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from services.copy_constants import (
    STATE_VERSION,
    is_special_first_segment,
)
from services.hash_cache import HashCache, hash_file
from services.mirror_check import is_reparse_point
from services.state_store import (
    StateData,
    StateFile,
    now_iso,
)
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = [
    "list_user_files",
    "scan_destination",
]


# --- Публичное ---

def list_user_files(destination: str) -> list[str]:
    """Быстрый обход: относительные пути user-файлов.

    Без чтения содержимого, без хэширования. Используется
    вызывающим для оценки total прогресса.
    """
    if not destination:
        return []
    base = Path(destination)
    if not base.is_dir():
        return []

    result: list[str] = []
    try:
        for root, dirs, names in os.walk(destination):
            rel_root = os.path.relpath(root, destination)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]
            dirs[:] = [
                d for d in dirs
                if not is_reparse_point(
                    os.path.join(root, d)
                )
            ]
            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, destination)
                first = rel.split(os.sep, 1)[0]
                if is_special_first_segment(first):
                    continue
                result.append(rel)
    except OSError as exc:
        logger.warning("list_user_files: %r", exc)
    return result


def scan_destination(
    destination: str,
    hash_cache: HashCache | None = None,
    *,
    file_list: list[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> StateData:
    """Строит StateData по текущему содержимому destination.

    file_list — заранее собранный список путей. Если не передан,
    вызывается list_user_files() (без прогресса по сбору).

    on_progress(processed, total) — вызывается по каждому
    обработанному файлу. total = len(file_list).
    """
    if not destination:
        return _empty_state()

    base = Path(destination)
    if not base.is_dir():
        logger.debug(
            "scan_destination: не директория %r", destination,
        )
        return _empty_state()

    if file_list is None:
        file_list = list_user_files(destination)

    total = len(file_list)
    files: list[StateFile] = []

    for idx, rel in enumerate(file_list, 1):
        full = os.path.join(destination, rel)

        st = _stat_safe(full)
        if st is not None:
            sha = _hash_for(full, rel, st, hash_cache)
            if sha is not None:
                files.append(StateFile(
                    path=rel,
                    sha256=sha,
                    size=st.st_size,
                    mtime=_iso_mtime(st),
                ))

        if on_progress is not None:
            try:
                on_progress(idx, total)
            except Exception as exc:
                logger.debug("scan on_progress: %r", exc)

    empty_dirs = _list_empty_dirs(destination)
    total_size = sum(f.size for f in files)

    return StateData(
        version=STATE_VERSION,
        created_at=now_iso(),
        kind="",
        source="",
        files=files,
        empty_dirs=empty_dirs,
        summary={
            "files_count": len(files),
            "empty_dirs_count": len(empty_dirs),
            "total_size": total_size,
            "new_blobs_count": 0,
            "new_blobs_bytes": 0,
        },
    )


# --- Вспомогательное ---

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


def _list_empty_dirs(destination: str) -> list[str]:
    """Пустые директории destination (без файлов и подкаталогов).

    Обход отдельный от обхода файлов — семантика «пустая =
    нет файлов и нет подкаталогов» сохраняется.
    """
    result: list[str] = []
    try:
        for root, dirs, names in os.walk(destination):
            rel_root = os.path.relpath(root, destination)
            had_dirs = bool(dirs)
            had_names = bool(names)

            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]

            dirs[:] = [
                d for d in dirs
                if not is_reparse_point(
                    os.path.join(root, d)
                )
            ]

            if (
                not had_dirs
                and not had_names
                and rel_root != "."
            ):
                result.append(rel_root)
    except OSError as exc:
        logger.debug("_list_empty_dirs: %r", exc)
    return result


def _stat_safe(path: str) -> os.stat_result | None:
    try:
        return os.stat(path)
    except OSError as exc:
        logger.debug("stat %s: %r", path, exc)
        return None


def _iso_mtime(st: os.stat_result) -> str:
    try:
        return datetime.fromtimestamp(
            st.st_mtime,
        ).isoformat(timespec="milliseconds")
    except (OSError, ValueError, OverflowError) as exc:
        logger.debug("iso_mtime: %r", exc)
        return ""


def _hash_for(
    full: str,
    rel: str,
    st: os.stat_result,
    cache: HashCache | None,
) -> str | None:
    if cache is not None and cache.enabled:
        entry = cache.get(rel)
        if (
            entry is not None
            and entry.size == st.st_size
            and entry.dst_mtime_ns == st.st_mtime_ns
        ):
            return entry.sha256

    try:
        return hash_file(full)
    except OSError as exc:
        logger.debug("hash %s: %r", full, exc)
        return None
