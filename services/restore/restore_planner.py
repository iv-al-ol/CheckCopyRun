"""Планирование restore по state-файлу.

Сравнивает целевое состояние (StateData из state-файла) с
текущим (StateData из scan_destination) и строит список действий.

Пути в StateData могут быть с любыми разделителями (`/` или `\\`)
— нормализация к `/` выполняется при построении плана.

План строится без записи в ФС, только чтение.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from services.cas.blob_store import BlobStore
from services.cas.state_store import StateData, StateFile
from services.common.path_norm import norm_path
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = ["RestorePlan", "build_plan"]


@dataclass
class RestorePlan:
    to_restore: list[tuple[StateFile, Path]] = field(
        default_factory=list,
    )
    to_delete_files: list[str] = field(default_factory=list)
    create_dirs: list[str] = field(default_factory=list)
    needed_dirs: set[str] = field(default_factory=set)
    missing_blobs: list[StateFile] = field(default_factory=list)
    skipped_files: int = 0

    @property
    def total_actions(self) -> int:
        return (
            len(self.to_restore)
            + len(self.to_delete_files)
            + len(self.create_dirs)
        )

    @property
    def has_changes(self) -> bool:
        return self.total_actions > 0


def build_plan(
    target: StateData,
    current: StateData,
    blobs: BlobStore,
) -> RestorePlan:
    """Строит план restore к target из current."""
    plan = RestorePlan()

    current_map: dict[str, StateFile] = {
        norm_path(f.path): f for f in current.files
    }
    target_paths: set[str] = set()

    for f in target.files:
        key = norm_path(f.path)
        target_paths.add(key)
        cur = current_map.get(key)
        if cur is not None and cur.sha256 == f.sha256:
            plan.skipped_files += 1
            continue
        blob = blobs.get(f.sha256)
        if blob is None:
            plan.missing_blobs.append(f)
            continue
        plan.to_restore.append((f, blob))

    for key in current_map:
        if key not in target_paths:
            plan.to_delete_files.append(key)

    plan.create_dirs = list(target.empty_dirs)
    plan.needed_dirs = _compute_needed_dirs(target)

    if plan.missing_blobs:
        logger.warning(
            "План restore: %d файлов без blob-а (не восстановить)",
            len(plan.missing_blobs),
        )
    logger.debug(
        "План restore: restore=%d, delete=%d, mkdir=%d, "
        "skip=%d, missing=%d",
        len(plan.to_restore),
        len(plan.to_delete_files),
        len(plan.create_dirs),
        plan.skipped_files,
        len(plan.missing_blobs),
    )
    return plan


# --- Вспомогательное ---



def _compute_needed_dirs(target: StateData) -> set[str]:
    """Все директории, которые обязаны существовать после restore.

    Включает:
      • empty_dirs target и всех их предков;
      • предков всех файлов target.

    Возвращает нормализованные (`/`) пути. Используется
    cleanup-ом пустых директорий, чтобы не удалить лишнего.
    """
    dirs: set[str] = set()

    for d in target.empty_dirs:
        p = norm_path(d)
        parts = p.split("/")
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))

    for f in target.files:
        p = norm_path(f.path)
        parts = p.split("/")
        # Предки (без самого файла).
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))

    return dirs
