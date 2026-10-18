"""Сравнение двух файлов с учётом кэша хэшей.

Логика:
  1. Разный размер → DIFFERENT сразу, без чтения.
  2. Есть запись в кэше с тем же размером:
     • оба stat совпали с кэшем → SAME без чтения;
     • только src изменился → хэш src, сравнить с кэшем;
     • только dst изменился → хэш dst, сравнить с кэшем;
     • оба изменились → хэш обоих.
  3. Кэша нет → хэш обоих.

Кэш обновляется по ходу. При выключенном кэше — fallback на
filecmp.cmp(shallow=False).
"""

from __future__ import annotations

import filecmp
import os
from dataclasses import dataclass
from enum import Enum

from services.hash_cache import HashCache, hash_file
from utils.logger import get_logger

logger = get_logger(__name__)


class ComparisonResult(Enum):
    SAME = "same"
    DIFFERENT = "different"


@dataclass
class CompareOutcome:
    """Результат сравнения.

    src_hash — хэш текущего src, если удалось получить без
    лишнего чтения (из кэша или из свежего расчёта). Caller
    переиспользует его после copy2 для записи в кэш.
    """

    result: ComparisonResult
    src_hash: str | None
    src_size: int
    src_mtime_ns: int
    used_cache: bool


def files_identical(
    src_path: str,
    dst_path: str,
    rel_path: str,
    cache: HashCache,
) -> CompareOutcome:
    """Сравнивает src и dst. Обновляет cache по ходу."""
    src_stat = os.stat(src_path)
    dst_stat = os.stat(dst_path)

    # 1. Разный размер — точно разные, без чтения.
    if src_stat.st_size != dst_stat.st_size:
        if cache.enabled:
            cache.remove(rel_path)
        return CompareOutcome(
            result=ComparisonResult.DIFFERENT,
            src_hash=None,
            src_size=src_stat.st_size,
            src_mtime_ns=src_stat.st_mtime_ns,
            used_cache=False,
        )

    # 2. Кэш выключен — legacy-путь.
    if not cache.enabled:
        return _legacy_compare(src_path, dst_path, src_stat)

    cached = cache.get(rel_path)

    # 3. Кэша нет или размер в нём другой — хэш обоих.
    if cached is None or cached.size != src_stat.st_size:
        return _hash_both(
            src_path, dst_path, rel_path, cache,
            src_stat, dst_stat,
        )

    # 4. Кэш есть и размер совпадает.
    src_unchanged = cached.src_mtime_ns == src_stat.st_mtime_ns
    dst_unchanged = cached.dst_mtime_ns == dst_stat.st_mtime_ns

    if src_unchanged and dst_unchanged:
        # Оба не менялись — SAME без чтения.
        return CompareOutcome(
            result=ComparisonResult.SAME,
            src_hash=cached.sha256,
            src_size=src_stat.st_size,
            src_mtime_ns=src_stat.st_mtime_ns,
            used_cache=True,
        )

    if src_unchanged and not dst_unchanged:
        # Изменился только dst. Хэшируем его.
        try:
            dst_hash = hash_file(dst_path, cache.algorithm)
        except OSError as exc:
            logger.debug("hash dst %s: %r", dst_path, exc)
            return _hash_both(
                src_path, dst_path, rel_path, cache,
                src_stat, dst_stat,
            )

        if dst_hash == cached.sha256:
            # Содержимое совпадает — файлы одинаковы.
            cache.update_stats(
                rel_path, dst_mtime_ns=dst_stat.st_mtime_ns,
            )
            return CompareOutcome(
                result=ComparisonResult.SAME,
                src_hash=cached.sha256,
                src_size=src_stat.st_size,
                src_mtime_ns=src_stat.st_mtime_ns,
                used_cache=True,
            )

        # Содержимое разное. Хэш src берём из кэша.
        return CompareOutcome(
            result=ComparisonResult.DIFFERENT,
            src_hash=cached.sha256,
            src_size=src_stat.st_size,
            src_mtime_ns=src_stat.st_mtime_ns,
            used_cache=True,
        )

    if not src_unchanged and dst_unchanged:
        # Изменился только src. Хэшируем его.
        try:
            src_hash = hash_file(src_path, cache.algorithm)
        except OSError as exc:
            logger.debug("hash src %s: %r", src_path, exc)
            return _hash_both(
                src_path, dst_path, rel_path, cache,
                src_stat, dst_stat,
            )

        if src_hash == cached.sha256:
            # Содержимое то же, только mtime изменился.
            cache.update_stats(
                rel_path, src_mtime_ns=src_stat.st_mtime_ns,
            )
            return CompareOutcome(
                result=ComparisonResult.SAME,
                src_hash=src_hash,
                src_size=src_stat.st_size,
                src_mtime_ns=src_stat.st_mtime_ns,
                used_cache=True,
            )

        return CompareOutcome(
            result=ComparisonResult.DIFFERENT,
            src_hash=src_hash,
            src_size=src_stat.st_size,
            src_mtime_ns=src_stat.st_mtime_ns,
            used_cache=True,
        )

    # 5. Оба изменились — хэшируем оба.
    return _hash_both(
        src_path, dst_path, rel_path, cache,
        src_stat, dst_stat,
    )


def _hash_both(
    src_path: str,
    dst_path: str,
    rel_path: str,
    cache: HashCache,
    src_stat,
    dst_stat,
) -> CompareOutcome:
    try:
        src_hash = hash_file(src_path, cache.algorithm)
        dst_hash = hash_file(dst_path, cache.algorithm)
    except OSError as exc:
        logger.debug(
            "hash %s / %s: %r", src_path, dst_path, exc,
        )
        # Не смогли прочитать — считаем разными, cache не трогаем.
        return CompareOutcome(
            result=ComparisonResult.DIFFERENT,
            src_hash=None,
            src_size=src_stat.st_size,
            src_mtime_ns=src_stat.st_mtime_ns,
            used_cache=False,
        )

    if src_hash == dst_hash:
        cache.put(
            rel_path,
            size=src_stat.st_size,
            src_mtime_ns=src_stat.st_mtime_ns,
            dst_mtime_ns=dst_stat.st_mtime_ns,
            sha256=src_hash,
        )
        return CompareOutcome(
            result=ComparisonResult.SAME,
            src_hash=src_hash,
            src_size=src_stat.st_size,
            src_mtime_ns=src_stat.st_mtime_ns,
            used_cache=False,
        )

    return CompareOutcome(
        result=ComparisonResult.DIFFERENT,
        src_hash=src_hash,
        src_size=src_stat.st_size,
        src_mtime_ns=src_stat.st_mtime_ns,
        used_cache=False,
    )


def _legacy_compare(
    src_path: str,
    dst_path: str,
    src_stat,
) -> CompareOutcome:
    try:
        same = filecmp.cmp(src_path, dst_path, shallow=False)
    except Exception as exc:
        logger.debug("filecmp.cmp упал: %r", exc)
        same = False

    return CompareOutcome(
        result=(
            ComparisonResult.SAME
            if same
            else ComparisonResult.DIFFERENT
        ),
        src_hash=None,
        src_size=src_stat.st_size,
        src_mtime_ns=src_stat.st_mtime_ns,
        used_cache=False,
    )
