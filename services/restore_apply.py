"""Применение плана restore к файловой системе.

Порядок:
  1. Восстановить файлы из blob-ов (mkdir предков по мере
     необходимости).
  2. Создать пустые директории из плана.
  3. Удалить лишние файлы.
  4. Удалить опустевшие директории, не входящие в needed_dirs.

Пути сравниваются в нормализованном виде (`/`), чтобы
работать и на Windows, и на posix, и не зависеть от того,
какие разделители попали в state-файл.

Защита от path traversal: пути из state проверяются на выход
за пределы destination. Служебные сегменты (!CCRun, !Backup_*)
пропускаются.
"""

from __future__ import annotations

import os
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
    """Применяет план к destination."""
    result = ApplyResult()
    total = plan.total_actions
    processed = 0
    base = Path(destination)

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
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(dst) + TMP_SUFFIX
            try:
                shutil.copy2(str(blob_path), tmp)
                os.replace(tmp, str(dst))
            except Exception:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
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
            _safe_path(base, rel)   # валидация
            target_dir = base / rel
            if not target_dir.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
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
            _safe_path(base, rel)   # валидация
            p = base / rel
            if p.is_file():
                p.unlink()
                result.deleted_files += 1
        except ValueError as exc:
            logger.warning("delete: %r", exc)
            result.errors += 1
        except OSError as exc:
            logger.warning("delete %s: %r", rel, exc)
            result.errors += 1

        processed += 1
        _emit(on_progress, processed, total)

    # 4. Cleanup пустых директорий
    try:
        result.deleted_dirs = _cleanup_empty_dirs(
            destination, plan.needed_dirs,
        )
    except Exception as exc:
        logger.warning("cleanup empty dirs: %r", exc)
        result.errors += 1

    return result


# --- Вспомогательное ---

def _norm(p: str) -> str:
    """Приводит path к прямым слэшам для сравнения."""
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


def _safe_path(base: Path, rel: str) -> Path:
    """Проверяет, что путь внутри base и не служебный."""
    first = rel.replace("\\", "/").split("/", 1)[0]
    if is_special_first_segment(first):
        raise ValueError(
            f"Служебный путь в state: {rel!r}"
        )
    target = (base / rel).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Небезопасный путь в state: {rel!r}"
        ) from exc
    return target


def _cleanup_empty_dirs(
    destination: str, needed: set[str],
) -> int:
    """Удаляет пустые директории, не входящие в needed.

    Обход снизу вверх. Пропускает служебные корневые папки.
    Сравнение путей — по нормализованным (`/`) строкам.
    """
    base = Path(destination).resolve()
    needed_norm = {_norm(p) for p in needed}
    all_dirs: list[Path] = []

    try:
        for root, dirs, _names in os.walk(destination):
            rel_root = os.path.relpath(root, destination)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]
            for d in dirs:
                all_dirs.append(Path(root) / d)
    except OSError as exc:
        logger.debug("os.walk cleanup: %r", exc)
        return 0

    all_dirs.sort(
        key=lambda p: len(p.parts), reverse=True,
    )

    deleted = 0
    for d in all_dirs:
        try:
            rel = str(d.relative_to(base))
        except ValueError:
            continue
        if _norm(rel) in needed_norm:
            continue
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                deleted += 1
        except OSError as exc:
            logger.debug("rmdir %s: %r", d, exc)

    return deleted
