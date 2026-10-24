"""Предварительная проверка для режима зеркала.

Поддержка длинных путей: walk и stat через long_io.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from core import long_io
from core.paths import to_long_path
from services.common.copy_constants import is_special_first_segment
from utils.logger import get_logger

logger = get_logger(__name__)

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse_point(path: str) -> bool:
    try:
        st = long_io.stat(path)
    except OSError as exc:
        logger.debug("stat %s: %r", path, exc)
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


@dataclass
class MirrorStats:
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
        if not self.files_to_remove and not self.dirs_to_remove:
            return False
        return self.files_ratio > 0.5


def scan_mirror_diff(
    source: str,
    destination: str,
) -> MirrorStats:
    stats = MirrorStats()
    if not source or not destination:
        return stats

    src_top = to_long_path(source)
    dst_top = to_long_path(destination)
    if not long_io.isdir(src_top) or not long_io.isdir(dst_top):
        return stats

    for root, dirs, names in long_io.walk(dst_top):
        rel_root = os.path.relpath(root, dst_top)

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
            rel = os.path.relpath(full, dst_top)

            if rel_root == "." and is_special_first_segment(
                rel.split(os.sep, 1)[0]
            ):
                continue

            stats.total_destination_files += 1

            src_path = os.path.join(src_top, rel)
            if not long_io.isfile(src_path):
                stats.files_to_remove.append(rel)

        for d in dirs:
            full = os.path.join(root, d)
            rel = os.path.relpath(full, dst_top)
            stats.total_destination_dirs += 1

            src_path = os.path.join(src_top, rel)
            if not long_io.isdir(src_path):
                stats.dirs_to_remove.append(rel)

    logger.debug(
        "Режим зеркала (pre-scan): %d/%d файлов, %d директорий",
        len(stats.files_to_remove),
        stats.total_destination_files,
        len(stats.dirs_to_remove),
    )
    return stats
