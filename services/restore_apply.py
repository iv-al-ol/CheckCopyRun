"""Применение плана restore к файловой системе.

Поддержка длинных путей: I/O через long_io.

_safe_path возвращает Path: так удобнее работать с родителем
(dst.parent) и str-конверсией для long_io. Все I/O-вызовы
принимают str — Path конвертируется через str() на месте.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core import long_io
from core.paths import to_long_path
from services.copy_constants import (
    TMP_SUFFIX,
    is_special_first_segment,
)
from services.restore_planner import RestorePlan
from services.state_store import StateData
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = ["ApplyResult", "apply_plan"]


@dataclass
class ApplyResult:
    restored: int = 0
    deleted_files: int = 0
    created_dirs: int = 0
    deleted_dirs: int = 0
    errors: int = 0
    cancelled: bool = False


def apply_plan(
    plan: RestorePlan,
    target: StateData,
    destination: str,
    on_progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> ApplyResult:
    result = ApplyResult()
    total = plan.total_actions
    processed = 0
    base = to_long_path(destination)

    # 1. Restore
    for state_file, blob_path in plan.to_restore:
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = True
            return result
        try:
            dst = _safe_path(base, state_file.path)
        except ValueError as exc:
            logger.warning("restore: %r", exc)
            result.errors += 1
            processed += 1
            _emit(on_progress, processed, total)
            continue

        try:
            long_io.makedirs(str(dst.parent), exist_ok=True)
            tmp = str(dst) + TMP_SUFFIX
            try:
                long_io.copy2(str(blob_path), tmp)
                long_io.replace(tmp, str(dst))
            except Exception:
                try:
                    if long_io.exists(tmp):
                        long_io.remove(tmp)
                except OSError:
                    pass
                raise
            result.restored += 1
        except Exception as exc:
            logger.error(
                "restore %s: %r", state_file.path, exc,
            )
            result.errors += 1

        processed += 1
        _emit(on_progress, processed, total)

    # 2. Empty dirs
    for rel in plan.create_dirs:
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = True
            return result
        try:
            _safe_path(base, rel)
            target_dir = os.path.join(base, rel)
            if not long_io.exists(target_dir):
                long_io.makedirs(target_dir, exist_ok=True)
                result.created_dirs += 1
        except ValueError as exc:
            logger.warning("mkdir: %r", exc)
            result.errors += 1
        except OSError as exc:
            logger.warning("mkdir %s: %r", rel, exc)
            result.errors += 1

        processed += 1
        _emit(on_progress, processed, total)

    # 3. Delete extra files
    for rel in plan.to_delete_files:
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = True
            return result
        try:
            _safe_path(base, rel)
            p = os.path.join(base, rel)
            if long_io.isfile(p):
                long_io.remove(p)
                result.deleted_files += 1
        except ValueError as exc:
            logger.warning("delete: %r", exc)
            result.errors += 1
        except OSError as exc:
            logger.warning("delete %s: %r", rel, exc)
            result.errors += 1

        processed += 1
        _emit(on_progress, processed, total)

    # 4. Cleanup
    try:
        result.deleted_dirs = _cleanup_empty_dirs(
            destination, plan.needed_dirs,
        )
    except Exception as exc:
        logger.warning("cleanup empty dirs: %r", exc)
        result.errors += 1

    return result


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def _emit(
    cb: Callable[[int, int], None] | None,
    processed: int, total: int,
) -> None:
    if cb is None:
        return
    try:
        cb(processed, total)
    except Exception as exc:
        logger.debug("on_progress apply_plan: %r", exc)


def _safe_path(base: str, rel: str) -> Path:
    """Проверяет, что путь внутри base и не служебный.

    Возвращает Path — для удобной работы с .parent и str()
    при передаче в long_io.
    """
    first = rel.replace("\\", "/").split("/", 1)[0]
    if is_special_first_segment(first):
        raise ValueError(
            f"Служебный путь в state: {rel!r}"
        )
    target = os.path.normpath(os.path.join(base, rel))
    base_norm = os.path.normpath(base)
    if not target.startswith(base_norm + os.sep):
        if target != base_norm:
            raise ValueError(
                f"Небезопасный путь в state: {rel!r}"
            )
    return Path(target)


def _cleanup_empty_dirs(
    destination: str, needed: set[str],
) -> int:
    base = to_long_path(destination)
    needed_norm = {_norm(p) for p in needed}
    all_dirs: list[str] = []

    try:
        for root, dirs, _names in long_io.walk(base):
            rel_root = os.path.relpath(root, base)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]
            for d in dirs:
                all_dirs.append(os.path.join(root, d))
    except OSError as exc:
        logger.debug("walk cleanup: %r", exc)
        return 0

    all_dirs.sort(
        key=lambda p: p.count(os.sep), reverse=True,
    )

    deleted = 0
    for d in all_dirs:
        try:
            rel = os.path.relpath(d, base)
        except ValueError:
            continue
        if _norm(rel) in needed_norm:
            continue
        try:
            if long_io.isdir(d) and not long_io.listdir(d):
                long_io.rmdir(d)
                deleted += 1
        except OSError as exc:
            logger.debug("rmdir %s: %r", d, exc)

    return deleted
