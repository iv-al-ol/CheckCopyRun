"""Проверка свободного места перед копированием.

Оценивает, сколько байт будет записано в destination:
  • новые файлы (их нет в destination) — их размер;
  • заменяемые файлы (есть, но отличаются) — их размер (для новой
    версии) + размер старой (если create_backup=True);
  • идентичные файлы (размер и mtime_ns совпадают) — пропускаются.

Оценка быстрая: без чтения содержимого, только stat. Идентичность
определяется по паре (размер, mtime_ns). Для файлов, у которых
это совпало с dst, копирование всё равно их пропустит — так что
оценка совпадает с реальной работой.

Если создать/прочитать не удаётся (сетевой диск недоступен,
неожиданная ошибка ФС) — возвращает None, и вызывающий код
продолжает без проверки.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from services.copy_constants import is_special_first_segment
from utils.logger import get_logger

logger = get_logger(__name__)

_KB = 1024
_MB = 1024 * _KB
_GB = 1024 * _MB
_TB = 1024 * _GB


@dataclass
class DiskSpaceCheck:
    """Результат оценки свободного места."""

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
        """True, если места хватает с учётом запаса."""
        return (
            self.needed_bytes + self.margin_bytes
            <= self.available_bytes
        )


# --- Форматирование ---

def format_bytes(n: int) -> str:
    """Человекочитаемый размер: '1.5 ГБ', '234 МБ', '12 КБ'."""
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


# --- Оценка ---

def _compute_margin(available: int) -> int:
    """Запас поверх нужного места.

    5% от доступного, но не меньше 10 МБ и не больше 500 МБ.
    Так на маленьких дисках не блокируем разумные копирования,
    а на больших оставляем адекватный буфер.
    """
    margin = int(available * 0.05)
    if margin < 10 * _MB:
        margin = 10 * _MB
    if margin > 500 * _MB:
        margin = 500 * _MB
    return margin


def _walk_source(
    source: str,
) -> tuple[int, list[str]] | None:
    """Все относительные пути файлов из source. None при ошибке."""
    try:
        result: list[str] = []

        for root, dirs, names in os.walk(source):
            rel_root = os.path.relpath(root, source)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]

            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, source)

                first = rel.split(os.sep, 1)[0]
                if is_special_first_segment(first):
                    continue

                result.append(rel)

        return len(result), result
    except OSError as exc:
        logger.debug("os.walk source %s: %r", source, exc)
        return None


def check_disk_space(
    source: str,
    destination: str,
    create_backup: bool,
) -> DiskSpaceCheck | None:
    """Оценивает, хватит ли места на диске destination.

    Возвращает DiskSpaceCheck или None, если оценить невозможно
    (недоступен source/destination, ошибка ФС).
    """
    if not source or not destination:
        return None

    if not os.path.isdir(source):
        logger.debug("source не директория: %s", source)
        return None
    if not os.path.isdir(destination):
        logger.debug("destination не директория: %s", destination)
        return None

    walk = _walk_source(source)
    if walk is None:
        return None

    _, files = walk

    new_count = 0
    new_bytes = 0

    replaced_count = 0
    replaced_bytes = 0

    backup_count = 0
    backup_bytes = 0

    for rel in files:
        src_path = os.path.join(source, rel)
        dst_path = os.path.join(destination, rel)

        try:
            src_stat = os.stat(src_path)
        except OSError as exc:
            logger.debug("stat src %s: %r", src_path, exc)
            continue

        src_size = src_stat.st_size
        src_mtime_ns = src_stat.st_mtime_ns

        # Новый файл — нужно записать его полный размер.
        if not os.path.isfile(dst_path):
            new_count += 1
            new_bytes += src_size
            continue

        try:
            dst_stat = os.stat(dst_path)
        except OSError as exc:
            logger.debug("stat dst %s: %r", dst_path, exc)
            new_count += 1
            new_bytes += src_size
            continue

        # Одинаковый размер и mtime_ns → считаем идентичными.
        # Копирование их тоже пропустит — оценка совпадает.
        if (
            src_size == dst_stat.st_size
            and src_mtime_ns == dst_stat.st_mtime_ns
        ):
            continue

        # Замена: размер новой версии + возможно бэкап старой.
        replaced_count += 1
        replaced_bytes += src_size

        if create_backup:
            backup_count += 1
            backup_bytes += dst_stat.st_size

    needed = new_bytes + replaced_bytes + backup_bytes

    try:
        usage = shutil.disk_usage(destination)
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
