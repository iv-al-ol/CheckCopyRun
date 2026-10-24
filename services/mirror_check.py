
"""Предварительная проверка для режима зеркала.

Режим зеркала убирает из destination файлы и папки, которых нет
в source. Если это ошибка выбора source (пустая папка, отключён
сетевой диск) — можно потерять много данных, пусть даже они и
перемещаются в бэкап.

Перед стартом копирования считаем, сколько файлов будет убрано.
Если больше половины от общего числа файлов в destination —
требуем подтверждение пользователя (UI-часть — в итерации 3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from services.copy_constants import is_special_first_segment
from utils.logger import get_logger

logger = get_logger(__name__)

# FILE_ATTRIBUTE_REPARSE_POINT — Windows-атрибут symlink, junction
# и прочих reparse points.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse_point(path: str) -> bool:
    """True для symlink/junction. На не-Windows — False."""
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        logger.debug("stat %s: %r", path, exc)
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


@dataclass
class MirrorStats:
    """Разница между destination и source для режима зеркала."""

    files_to_remove: list[str] = field(default_factory=list)
    dirs_to_remove: list[str] = field(default_factory=list)
    total_destination_files: int = 0
    total_destination_dirs: int = 0

    @property
    def files_ratio(self) -> float:
        if self.total_destination_files <= 0:
            return 0.0
        return len(self.files_to_remove) / self.total_destination_files

    @property
    def requires_confirmation(self) -> bool:
        """True, если убирается больше половины файлов."""
        if not self.files_to_remove and not self.dirs_to_remove:
            return False
        return self.files_ratio > 0.5


def scan_mirror_diff(
    source: str,
    destination: str,
) -> MirrorStats:
    """Считает, что mirror уберёт из destination.

    Служебные папки (!CCRun, !Backup_*) и reparse points
    пропускаются — mirror их не трогает.
    """
    stats = MirrorStats()

    if not source or not destination:
        return stats
    if not os.path.isdir(source) or not os.path.isdir(destination):
        return stats

    for root, dirs, names in os.walk(destination):
        rel_root = os.path.relpath(root, destination)

        # Отфильтровать symlink/junction — не заходим внутрь.
        filtered: list[str] = []
        for d in dirs:
            full = os.path.join(root, d)
            if is_reparse_point(full):
                logger.warning(
                    "Режим зеркала: пропущен reparse point %s", full,
                )
                continue
            if rel_root == "." and is_special_first_segment(d):
                continue
            filtered.append(d)
        dirs[:] = filtered

        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, destination)

            if rel_root == "." and is_special_first_segment(
                rel.split(os.sep, 1)[0]
            ):
                continue

            stats.total_destination_files += 1

            src_path = os.path.join(source, rel)
            if not os.path.isfile(src_path):
                stats.files_to_remove.append(rel)

        for d in dirs:
            full = os.path.join(root, d)
            rel = os.path.relpath(full, destination)
            stats.total_destination_dirs += 1

            src_path = os.path.join(source, rel)
            if not os.path.isdir(src_path):
                stats.dirs_to_remove.append(rel)

    logger.debug(
        "Режим зеркала (pre-scan): %d/%d файлов, %d директорий "
        "к перемещению в бэкап",
        len(stats.files_to_remove),
        stats.total_destination_files,
        len(stats.dirs_to_remove),
    )

    return stats
