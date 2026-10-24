"""Снимок дерева источника по stat и дифф двух снимков.

Главное ограничение производительности: **никакого хэширования
и чтения содержимого**. Только `stat` (размер + `st_mtime_ns`)
через `core.long_io`. Это позволяет опрашивать источник с
интервалом в единицы минут, не нагружая диск.

Формат снимка совместим с JSON и персистентной базой
(`monitor_state`):

    {
      "files":  {"rel/path": [size, mtime_ns], ...},
      "total_files": 12,
      "total_bytes": 34567,
      "max_mtime_ns": 1700000000000000000,
      "truncated": false,
      "source": "C:/build"
    }

Если пользовательских файлов больше `MONITOR_INDEX_MAX_FILES`,
посуточный индекс не хранится (`truncated=True`, `files={}`),
а изменения определяются по агрегатам `(total_files,
total_bytes, max_mtime_ns)`. Это защищает базу снимков от
разрастания на деревьях вида `node_modules`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from config.constants import MONITOR_INDEX_MAX_FILES
from core import long_io
from core.paths import to_long_path
from services.common.copy_constants import is_special_first_segment
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "SnapshotDiff",
    "build_snapshot",
    "diff_snapshots",
    "snapshot_from_dict",
    "snapshot_to_dict",
]


@dataclass
class SnapshotDiff:
    """Разница двух снимков источника."""

    added: int = 0
    modified: int = 0
    removed: int = 0
    total_changed: int = 0

    @property
    def has_changes(self) -> bool:
        return self.total_changed > 0


def build_snapshot(
    source: str,
    *,
    max_files: int = MONITOR_INDEX_MAX_FILES,
) -> dict | None:
    """Stat-only снимок дерева источника.

    Возвращает `None`, если источник недоступен (нет пути, не
    директория, нет прав). В этом случае вызывающая сторона
    должна пропустить профиль, а не трактовать это как
    «всё удалено».

    Args:
        source: Путь к папке-источнику.
        max_files: Порог, выше которого индекс файлов не хранится.

    Returns:
        Словарь снимка или `None`.
    """
    if not source:
        return None

    top = to_long_path(source)
    if not long_io.isdir(top):
        logger.debug("build_snapshot: не директория %r", source)
        return None

    files: dict[str, list[int]] = {}
    total_files = 0
    total_bytes = 0
    max_mtime_ns = 0
    truncated = False

    try:
        for root, dirs, names in long_io.walk(top):
            rel_root = os.path.relpath(root, top)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]

            for name in names:
                if truncated:
                    break

                full = os.path.join(root, name)
                rel = os.path.relpath(full, top)
                first = rel.split(os.sep, 1)[0]
                if is_special_first_segment(first):
                    continue

                st = _stat_safe(full)
                if st is None:
                    continue

                total_files += 1
                total_bytes += st.st_size
                if st.st_mtime_ns > max_mtime_ns:
                    max_mtime_ns = st.st_mtime_ns

                if total_files > max_files:
                    truncated = True
                    files.clear()
                    break

                files[rel.replace(os.sep, "/")] = [
                    st.st_size, st.st_mtime_ns,
                ]
    except OSError as exc:
        logger.warning("build_snapshot %r: %r", source, exc)
        return None

    return {
        "source": source,
        "files": files,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "max_mtime_ns": max_mtime_ns,
        "truncated": truncated,
    }


def diff_snapshots(
    old: dict | None, new: dict | None,
) -> SnapshotDiff:
    """Сравнивает два снимка одного источника.

    Если один из снимков `None` — возвращает пустой дифф: нет
    базы для сравнения (первый запуск) либо источник недоступен.

    Args:
        old: Предыдущий снимок.
        new: Текущий снимок.

    Returns:
        `SnapshotDiff` с количеством добавленных, изменённых и
        удалённых файлов.
    """
    if old is None or new is None:
        return SnapshotDiff()

    old_truncated = bool(old.get("truncated"))
    new_truncated = bool(new.get("truncated"))

    if old_truncated or new_truncated:
        return _diff_by_aggregate(old, new)

    old_files: dict = old.get("files") or {}
    new_files: dict = new.get("files") or {}

    added = 0
    modified = 0
    for rel, meta in new_files.items():
        prev = old_files.get(rel)
        if prev is None:
            added += 1
        elif list(prev) != list(meta):
            modified += 1

    removed = sum(
        1 for rel in old_files if rel not in new_files
    )

    return SnapshotDiff(
        added=added,
        modified=modified,
        removed=removed,
        total_changed=added + modified + removed,
    )


def _diff_by_aggregate(
    old: dict, new: dict,
) -> SnapshotDiff:
    """Грубая оценка изменений по агрегатам (без индекса)."""
    if (
        int(old.get("total_files") or 0)
        == int(new.get("total_files") or 0)
        and int(old.get("total_bytes") or 0)
        == int(new.get("total_bytes") or 0)
        and int(old.get("max_mtime_ns") or 0)
        == int(new.get("max_mtime_ns") or 0)
    ):
        return SnapshotDiff()

    total = max(
        int(new.get("total_files") or 0),
        int(old.get("total_files") or 0),
    )
    return SnapshotDiff(
        modified=total, total_changed=total,
    )


def _stat_safe(path: str) -> os.stat_result | None:
    try:
        return long_io.stat(path)
    except OSError as exc:
        logger.debug("stat %s: %r", path, exc)
        return None


def snapshot_to_dict(snapshot: dict) -> dict:
    """Нормализует снимок для записи в JSON."""
    return {
        "source": str(snapshot.get("source") or ""),
        "files": dict(snapshot.get("files") or {}),
        "total_files": int(snapshot.get("total_files") or 0),
        "total_bytes": int(snapshot.get("total_bytes") or 0),
        "max_mtime_ns": int(snapshot.get("max_mtime_ns") or 0),
        "truncated": bool(snapshot.get("truncated")),
    }


def snapshot_from_dict(data: dict | None) -> dict | None:
    """Читает снимок из JSON, отбрасывая некорректные записи."""
    if not isinstance(data, dict):
        return None

    raw_files = data.get("files")
    files: dict[str, list[int]] = {}
    if isinstance(raw_files, dict):
        for rel, meta in raw_files.items():
            if (
                isinstance(rel, str)
                and isinstance(meta, list)
                and len(meta) == 2
            ):
                try:
                    files[rel] = [int(meta[0]), int(meta[1])]
                except (TypeError, ValueError):
                    continue

    return {
        "source": str(data.get("source") or ""),
        "files": files,
        "total_files": int(data.get("total_files") or 0),
        "total_bytes": int(data.get("total_bytes") or 0),
        "max_mtime_ns": int(data.get("max_mtime_ns") or 0),
        "truncated": bool(data.get("truncated")),
    }
