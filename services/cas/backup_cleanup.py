"""Политика хранения состояний + GC blob-ов.

Поддержка длинных путей: remove через long_io.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from core import long_io
from services.cas.backup_registry import collect_keep_hashes
from services.cas.blob_store import BlobStore
from services.cas.current_pointer import CurrentPointer
from services.cas.state_store import (
    StateStore,
    StateStoreError,
)
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = [
    "CleanupPolicy",
    "CleanupResult",
    "cleanup_states",
]


@dataclass
class CleanupPolicy:
    keep_last_enabled: bool = False
    keep_last_n: int = 10
    delete_older_enabled: bool = False
    delete_older_days: int = 30

    @property
    def is_active(self) -> bool:
        return (
            self.keep_last_enabled
            or self.delete_older_enabled
        )


@dataclass
class CleanupResult:
    total_found: int = 0
    deleted: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    blobs_deleted: int = 0
    blobs_freed_bytes: int = 0

    @property
    def deleted_count(self) -> int:
        return len(self.deleted)


def cleanup_states(
    destination: str,
    policy: CleanupPolicy,
) -> CleanupResult:
    result = CleanupResult()

    if not policy.is_active:
        return result
    if not destination:
        return result

    try:
        store = StateStore(destination)
    except StateStoreError as exc:
        logger.warning(
            "cleanup_states: хранилище недоступно: %r", exc,
        )
        return result

    states = store.list()
    result.total_found = len(states)
    if not states:
        return result

    current = CurrentPointer(destination).load()
    current_name = current.state if current else ""

    to_delete: set[Path] = set()
    names_to_delete: set[str] = set()

    if (
        policy.keep_last_enabled
        and policy.keep_last_n >= 0
    ):
        keepers = set()
        for info in states[: policy.keep_last_n]:
            keepers.add(info.path)
        if current_name:
            for info in states:
                if info.path.name == current_name:
                    keepers.add(info.path)
                    break
        for info in states:
            if info.path in keepers:
                continue
            to_delete.add(info.path)
            names_to_delete.add(info.path.name)

    if (
        policy.delete_older_enabled
        and policy.delete_older_days >= 0
    ):
        cutoff = datetime.now() - timedelta(
            days=policy.delete_older_days,
        )
        for info in states:
            if info.timestamp is None:
                continue
            if info.timestamp >= cutoff:
                continue
            if info.path.name == current_name:
                continue
            to_delete.add(info.path)
            names_to_delete.add(info.path.name)

    if current_name:
        to_delete = {
            p for p in to_delete if p.name != current_name
        }
        names_to_delete.discard(current_name)

    for info in states:
        if info.path not in to_delete:
            continue
        try:
            long_io.remove(str(info.path))
            result.deleted.append(info.path.name)
            logger.info(
                "Удалено состояние по политике: %s",
                info.path.name,
            )
        except OSError as exc:
            result.errors.append((info.path.name, str(exc)))
            logger.warning(
                "Не удалось удалить state %s: %r",
                info.path.name, exc,
            )

    if result.deleted:
        try:
            keep = collect_keep_hashes(
                destination, exclude=names_to_delete,
            )
            blobs = BlobStore(destination)
            deleted, freed = blobs.gc(keep)
            result.blobs_deleted = deleted
            result.blobs_freed_bytes = freed
            if deleted:
                logger.info(
                    "GC blob-ов после очистки: "
                    "удалено %d, освобождено %d байт",
                    deleted, freed,
                )
        except Exception as exc:
            logger.warning("GC blob-ов упал: %r", exc)

    return result
