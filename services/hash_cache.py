"""Кэш SHA-256 для сравнения файлов при копировании.

Хранит снимок последнего подтверждённого совпадения source и
destination: размер (одинаковый для обоих), mtime_ns обоих
файлов и хэш содержимого. Позволяет сравнивать файлы по одному
stat без чтения, если ничего не менялось.

Файл кэша: <destination>/!CCRun/hashes.json. Атомарная запись
(tmp + os.replace). При отсутствии/повреждении/несовпадении
версии или алгоритма — молча стартует с пустым кэшем.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config.constants import HASH_CACHE_ALGORITHM
from services.copy_constants import (
    CCRUN_DIR_NAME,
    HASH_CACHE_FILENAME,
    HASH_CACHE_VERSION,
    TMP_SUFFIX,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_CHUNK_SIZE = 1024 * 1024   # 1 МБ


@dataclass
class CacheEntry:
    size: int
    src_mtime_ns: int
    dst_mtime_ns: int
    sha256: str


def hash_file(
    path: str, algorithm: str = HASH_CACHE_ALGORITHM,
) -> str:
    """Потоковый хэш файла. Возвращает hex digest."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class HashCache:
    """Кэш хэшей для одной директории назначения."""

    def __init__(
        self,
        destination: str,
        *,
        enabled: bool = True,
        algorithm: str = HASH_CACHE_ALGORITHM,
    ):
        self._destination = Path(destination)
        self._enabled = enabled
        self._algorithm = algorithm
        self._entries: dict[str, CacheEntry] = {}
        self._dirty = False

    # --- Публичное ---

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def algorithm(self) -> str:
        return self._algorithm

    def load(self) -> None:
        if not self._enabled:
            return

        path = self._path()
        if not path.is_file():
            logger.debug("Кэш хэшей отсутствует: %s", path)
            return

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as exc:
            logger.warning(
                "Не удалось прочитать кэш %s: %r", path, exc,
            )
            return

        if not isinstance(data, dict):
            logger.warning("Кэш %s: неожиданный формат", path)
            return

        if data.get("version") != HASH_CACHE_VERSION:
            logger.warning(
                "Кэш %s: версия %r != %r, игнорирую",
                path, data.get("version"), HASH_CACHE_VERSION,
            )
            return

        if data.get("algorithm") != self._algorithm:
            logger.warning(
                "Кэш %s: алгоритм %r != %r, игнорирую",
                path, data.get("algorithm"), self._algorithm,
            )
            return

        files = data.get("files") or {}
        if not isinstance(files, dict):
            return

        for rel, item in files.items():
            if not isinstance(item, dict):
                continue
            try:
                self._entries[rel] = CacheEntry(
                    size=int(item["size"]),
                    src_mtime_ns=int(item["src_mtime_ns"]),
                    dst_mtime_ns=int(item["dst_mtime_ns"]),
                    sha256=str(item["sha256"]),
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("Плохая запись %r: %r", rel, exc)

        logger.debug(
            "Загружено %d записей кэша из %s",
            len(self._entries), path,
        )

    def save(self) -> None:
        if not self._enabled or not self._dirty:
            return

        path = self._path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error(
                "Не удалось создать %s: %r", path.parent, exc,
            )
            return

        payload = {
            "version": HASH_CACHE_VERSION,
            "algorithm": self._algorithm,
            "created_at": datetime.now().isoformat(
                timespec="milliseconds",
            ),
            "files": {
                rel: {
                    "size": e.size,
                    "src_mtime_ns": e.src_mtime_ns,
                    "dst_mtime_ns": e.dst_mtime_ns,
                    "sha256": e.sha256,
                }
                for rel, e in self._entries.items()
            },
        }

        tmp = str(path) + TMP_SUFFIX
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(path))
            logger.debug(
                "Кэш хэшей сохранён: %d записей", len(self._entries),
            )
            self._dirty = False
        except Exception as exc:
            logger.error("Не удалось сохранить кэш %s: %r", path, exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError as cleanup_exc:
                logger.debug(
                    "cleanup %s: %r", tmp, cleanup_exc,
                )

    def get(self, rel_path: str) -> CacheEntry | None:
        return self._entries.get(rel_path)

    def put(
        self,
        rel_path: str,
        *,
        size: int,
        src_mtime_ns: int,
        dst_mtime_ns: int,
        sha256: str,
    ) -> None:
        self._entries[rel_path] = CacheEntry(
            size=size,
            src_mtime_ns=src_mtime_ns,
            dst_mtime_ns=dst_mtime_ns,
            sha256=sha256,
        )
        self._dirty = True

    def update_stats(
        self,
        rel_path: str,
        *,
        src_mtime_ns: int | None = None,
        dst_mtime_ns: int | None = None,
    ) -> None:
        e = self._entries.get(rel_path)
        if e is None:
            return
        if src_mtime_ns is not None:
            e.src_mtime_ns = src_mtime_ns
        if dst_mtime_ns is not None:
            e.dst_mtime_ns = dst_mtime_ns
        self._dirty = True

    def remove(self, rel_path: str) -> None:
        if rel_path in self._entries:
            del self._entries[rel_path]
            self._dirty = True

    def paths(self) -> list[str]:
        return list(self._entries.keys())

    def clear(self) -> None:
        if self._entries:
            self._entries.clear()
            self._dirty = True

    # --- Внутреннее ---

    def _path(self) -> Path:
        return self._destination / CCRUN_DIR_NAME / HASH_CACHE_FILENAME
