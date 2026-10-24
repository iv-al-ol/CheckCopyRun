"""Метка текущей версии destination для UI.

Поддержка длинных путей: обход через long_io.walk, stat через
long_io.stat.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from core import long_io
from core.paths import to_long_path
from services.blob_store import BlobStore
from services.copy_constants import (
    STATE_KIND_AUTO,
    is_special_first_segment,
)
from services.current_pointer import CurrentData, CurrentPointer
from services.state_scanner import scan_destination
from services.state_store import (
    StateData,
    StateFile,
    StateStore,
    StateStoreError,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_LABEL_DATETIME_FMT = "%d.%m.%Y %H:%M:%S"
_LABEL_PREFIX = "Текущая версия от"
_LABEL_SEP = " — "

_MTIME_TOLERANCE_NS = 10_000_000


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


# --- Сохранение (совместимость и для тестов) ---

def save_after_copy(destination: str) -> None:
    if not destination:
        return
    if not long_io.isdir(str(destination)):
        return

    try:
        data = scan_destination(destination)
        data.kind = STATE_KIND_AUTO
        data.source = ""

        blobs = BlobStore(destination)
        base = to_long_path(destination)
        new_count = 0
        new_bytes = 0
        for f in data.files:
            full = os.path.join(base, f.path)
            if not long_io.isfile(full):
                continue
            try:
                if blobs.put(full, f.sha256):
                    new_count += 1
                    new_bytes += f.size
            except Exception as exc:
                logger.debug(
                    "save_after_copy: blob put: %r", exc,
                )
        data.summary["new_blobs_count"] = new_count
        data.summary["new_blobs_bytes"] = new_bytes

        store = StateStore(destination)
        path = store.create(data)
        CurrentPointer(destination).save_copy(path.name)
    except Exception as exc:
        logger.warning("save_after_copy: %r", exc)


def save_after_restore(
    destination: str, backup_dir: str,
) -> None:
    if not destination:
        return
    if not long_io.isdir(str(destination)):
        return

    try:
        store = StateStore(destination)
    except StateStoreError:
        return

    target = Path(backup_dir)
    state_name = target.name if target.is_file() else backup_dir

    try:
        store.load(state_name)
    except StateStoreError as exc:
        logger.debug(
            "save_after_restore: state %r не найден: %r",
            state_name, exc,
        )
        return

    CurrentPointer(destination).save_restore(
        state_name, restored_from=state_name,
    )


# --- Метка версии ---

def build_label(destination: str) -> str:
    if not destination or not long_io.isdir(str(destination)):
        return ""

    cur = CurrentPointer(destination).load()

    if cur is None or not cur.state:
        latest = _latest_file_mtime(destination)
        if latest is None:
            return "Версия не определена"
        return (
            f"{_LABEL_PREFIX} "
            f"{latest.strftime(_LABEL_DATETIME_FMT)}"
        )

    try:
        store = StateStore(destination)
        state = store.load(cur.state)
    except StateStoreError as exc:
        logger.warning(
            "build_label: state %r не загружен: %r",
            cur.state, exc,
        )
        latest = _latest_file_mtime(destination)
        if latest is None:
            return "Версия не определена"
        return (
            f"{_LABEL_PREFIX} "
            f"{latest.strftime(_LABEL_DATETIME_FMT)}"
        )

    edited, latest = _scan_vs_state(destination, state)

    if not edited and not state.files and not state.empty_dirs:
        return "Папка пуста"

    dt = _label_datetime(
        cur, state, edited=edited, latest=latest,
    )
    suffix = _suffix_for_action(
        cur.last_action or "", edited=edited,
    )

    if dt is None:
        if suffix:
            return f"Текущая версия{_LABEL_SEP}{suffix}"
        return "Версия не определена"

    base = f"{_LABEL_PREFIX} {dt.strftime(_LABEL_DATETIME_FMT)}"
    if suffix:
        return f"{base}{_LABEL_SEP}{suffix}"
    return base


# --- Дата для метки ---

def _label_datetime(
    cur: CurrentData,
    state: StateData,
    *,
    edited: bool,
    latest: datetime | None,
) -> datetime | None:
    if edited:
        if latest is not None:
            return latest
        return _parse_iso(state.created_at)

    if cur.last_action in ("restore", "rollback"):
        return _parse_iso(state.created_at)

    if cur.last_action_at:
        dt = _parse_iso(cur.last_action_at)
        if dt is not None:
            return dt

    return _parse_iso(state.created_at)


def _suffix_for_action(
    last_action: str, *, edited: bool,
) -> str:
    if edited:
        if last_action == "restore":
            return (
                "изменено вручную после восстановления "
                "из бэкапа"
            )
        if last_action == "rollback":
            return "изменено вручную после отката"
        return "изменено вручную"

    if last_action == "restore":
        return "восстановлено из бэкапа"
    if last_action == "rollback":
        return "откат после отмены"
    return ""


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# --- Один проход ---

def _scan_vs_state(
    destination: str, state: StateData,
) -> tuple[bool, datetime | None]:
    top = to_long_path(destination)
    state_map: dict[str, StateFile] = {
        _norm(f.path): f for f in state.files
    }
    latest_ns = 0
    edited = False

    try:
        for root, dirs, names in long_io.walk(top):
            rel_root = os.path.relpath(root, top)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]
            for name in names:
                full = os.path.join(root, name)
                rel = _norm(os.path.relpath(full, top))
                first = rel.split("/", 1)[0]
                if is_special_first_segment(first):
                    continue
                try:
                    st = long_io.stat(full)
                except OSError:
                    continue

                if st.st_mtime_ns > latest_ns:
                    latest_ns = st.st_mtime_ns

                if edited:
                    continue

                sf = state_map.pop(rel, None)
                if sf is None:
                    edited = True
                    continue

                if not sf.mtime:
                    continue

                expected_ns = _to_ns(sf.mtime)
                if expected_ns is None:
                    continue

                if (
                    abs(st.st_mtime_ns - expected_ns)
                    > _MTIME_TOLERANCE_NS
                ):
                    edited = True
    except OSError as exc:
        logger.debug("_scan_vs_state: %r", exc)
        return True, _latest_file_mtime(destination)

    if not edited and state_map:
        edited = True

    latest: datetime | None = None
    if latest_ns > 0:
        try:
            latest = datetime.fromtimestamp(
                latest_ns / 1_000_000_000,
            )
        except (OSError, ValueError, OverflowError) as exc:
            logger.debug("mtime conversion: %r", exc)

    return edited, latest


def _to_ns(iso: str) -> int | None:
    try:
        dt = datetime.fromisoformat(iso)
        return int(dt.timestamp() * 1_000_000_000)
    except (ValueError, TypeError, OSError):
        return None


def _latest_file_mtime(
    destination: str,
) -> datetime | None:
    if not destination:
        return None
    top = to_long_path(destination)
    if not long_io.isdir(top):
        return None

    latest_ns = 0
    try:
        for root, dirs, files in long_io.walk(top):
            rel_root = os.path.relpath(root, top)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, top)
                first = rel.split(os.sep, 1)[0]
                if is_special_first_segment(first):
                    continue
                try:
                    st = long_io.stat(full)
                except OSError:
                    continue
                if st.st_mtime_ns > latest_ns:
                    latest_ns = st.st_mtime_ns
    except OSError as exc:
        logger.debug("_latest_file_mtime: %r", exc)
        return None

    if latest_ns == 0:
        return None
    try:
        return datetime.fromtimestamp(
            latest_ns / 1_000_000_000,
        )
    except (OSError, ValueError, OverflowError) as exc:
        logger.debug("mtime conversion: %r", exc)
        return None


def _norm(p: str) -> str:
    return p.replace("\\", "/")
