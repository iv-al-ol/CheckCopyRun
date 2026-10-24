"""Проверка свободного места перед копированием.

Поддержка длинных путей: stat через long_io, disk_usage через
long_io.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from core import long_io
from core.paths import to_long_path
from services.common.copy_constants import is_special_first_segment
from utils.logger import get_logger

logger = get_logger(__name__)

_KB = 1024
_MB = 1024 * _KB
_GB = 1024 * _MB
_TB = 1024 * _GB


@dataclass
class DiskSpaceCheck:
    needed_bytes: int
    available_bytes: int
    margin_bytes: int
    new_files_count: int
    new_files_bytes: int
    replaced_files_count: int
    replaced_files_bytes: int
    backup_files_count: int
    backup_files_bytes: int

    @property
    def ok(self) -> bool:
        return (
            self.needed_bytes + self.margin_bytes
            <= self.available_bytes
        )


def format_bytes(n: int) -> str:
    n = max(0, int(n))
    if n < _KB:
        return f"{n} Б"
    if n < _MB:
        return f"{n / _KB:.1f} КБ"
    if n < _GB:
        return f"{n / _MB:.1f} МБ"
    if n < _TB:
        return f"{n / _GB:.1f} ГБ"
    return f"{n / _TB:.1f} ТБ"


def _compute_margin(available: int) -> int:
    margin = int(available * 0.05)
    if margin < 10 * _MB:
        margin = 10 * _MB
    if margin > 500 * _MB:
        margin = 500 * _MB
    return margin


def _walk_source(source: str) -> list[str] | None:
    try:
        top = to_long_path(source)
        result: list[str] = []
        for root, dirs, names in long_io.walk(top):
            rel_root = os.path.relpath(root, top)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]
            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, top)
                first = rel.split(os.sep, 1)[0]
                if is_special_first_segment(first):
                    continue
                result.append(rel)
        return result
    except OSError as exc:
        logger.debug("walk source %s: %r", source, exc)
        return None


def check_disk_space(
    source: str,
    destination: str,
    create_backup: bool,
) -> DiskSpaceCheck | None:
    if not source or not destination:
        return None

    if not long_io.isdir(source):
        logger.debug("source не директория: %s", source)
        return None
    if not long_io.isdir(destination):
        logger.debug("destination не директория: %s", destination)
        return None

    files = _walk_source(source)
    if files is None:
        return None

    src_top = to_long_path(source)
    dst_top = to_long_path(destination)

    new_count = 0
    new_bytes = 0
    replaced_count = 0
    replaced_bytes = 0
    backup_count = 0
    backup_bytes = 0

    for rel in files:
        src_path = os.path.join(src_top, rel)
        dst_path = os.path.join(dst_top, rel)

        try:
            src_stat = long_io.stat(src_path)
        except OSError as exc:
            logger.debug("stat src %s: %r", src_path, exc)
            continue

        src_size = src_stat.st_size
        src_mtime_ns = src_stat.st_mtime_ns

        if not long_io.isfile(dst_path):
            new_count += 1
            new_bytes += src_size
            continue

        try:
            dst_stat = long_io.stat(dst_path)
        except OSError as exc:
            logger.debug("stat dst %s: %r", dst_path, exc)
            new_count += 1
            new_bytes += src_size
            continue

        if (
            src_size == dst_stat.st_size
            and src_mtime_ns == dst_stat.st_mtime_ns
        ):
            continue

        replaced_count += 1
        replaced_bytes += src_size

        if create_backup:
            backup_count += 1
            backup_bytes += dst_stat.st_size

    needed = new_bytes + replaced_bytes + backup_bytes

    try:
        usage = long_io.disk_usage(destination)
    except OSError as exc:
        logger.debug("disk_usage %s: %r", destination, exc)
        return None

    available = usage.free
    margin = _compute_margin(available)

    result = DiskSpaceCheck(
        needed_bytes=needed,
        available_bytes=available,
        margin_bytes=margin,
        new_files_count=new_count,
        new_files_bytes=new_bytes,
        replaced_files_count=replaced_count,
        replaced_files_bytes=replaced_bytes,
        backup_files_count=backup_count,
        backup_files_bytes=backup_bytes,
    )

    logger.debug(
        "disk_space: нужно %s, доступно %s, запас %s → ok=%s",
        format_bytes(needed),
        format_bytes(available),
        format_bytes(margin),
        result.ok,
    )
    return result
