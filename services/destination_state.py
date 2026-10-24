"""Метка текущей версии destination для UI.

Использует CAS: current.json + state-файлы. Собственного файла
destination_state.json больше нет — нужная информация уже в
current.json (last_action, last_action_at, state, restored_from)
и в state-файлах (created_at, files с mtime и sha256).

Manual-edit detection (один проход):
  • для каждого файла state сравниваем mtime из state с
    фактическим mtime файла (допуск 10 мс);
  • файл в destination, которого нет в state → редактирование;
  • файл из state, которого нет в destination → редактирование.

После первого обнаруженного отличия сравнение mtime
прекращается (edited=True), но обход продолжается — чтобы
собрать latest_mtime для метки «изменена вручную». Это
устраняет второй проход, который раньше был нужен для
_latest_file_mtime.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from services.blob_store import BlobStore
from services.copy_constants import (
    STATE_KIND_AUTO,
    is_special_first_segment,
)
from services.current_pointer import CurrentPointer
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

# Допуск на сравнение mtime: 10 мс. ISO-сериализация времени
# обрезает до миллисекунд — теряется максимум 1 мс.
_MTIME_TOLERANCE_NS = 10_000_000


def now_iso() -> str:
    """Текущее время в ISO 8601 с миллисекундами."""
    return datetime.now().isoformat(timespec="milliseconds")


# --- Сохранение (совместимость и для тестов) ---

def save_after_copy(destination: str) -> None:
    """Создаёт state и обновляет current."""
    if not destination:
        return
    if not Path(destination).is_dir():
        return

    try:
        data = scan_destination(destination)
        data.kind = STATE_KIND_AUTO
        data.source = ""

        blobs = BlobStore(destination)
        base = Path(destination)
        new_count = 0
        new_bytes = 0
        for f in data.files:
            full = base / f.path
            if not full.is_file():
                continue
            try:
                if blobs.put(str(full), f.sha256):
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
    """Обновляет current: last_action=restore."""
    if not destination:
        return
    if not Path(destination).is_dir():
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
    """Строка для UI. Пустая — если destination не задан/нет."""
    if not destination or not Path(destination).is_dir():
        return ""

    cur = CurrentPointer(destination).load()

    if cur is None or not cur.state:
        latest = _latest_file_mtime(destination)
        if latest is None:
            return "Версия не определена"
        return (
            f"Текущая версия файлов от "
            f"{latest.strftime(_LABEL_DATETIME_FMT)}"
        )

    try:
        store = StateStore(destination)
        state = store.load(cur.state)
    except StateStoreError as exc:
        logger.debug(
            "build_label: state %r не загружен: %r",
            cur.state, exc,
        )
        latest = _latest_file_mtime(destination)
        if latest is None:
            return "Версия не определена"
        return (
            f"Текущая версия файлов от "
            f"{latest.strftime(_LABEL_DATETIME_FMT)}"
        )

    edited, latest = _scan_vs_state(destination, state)

    if edited:
        if latest is not None:
            return (
                f"Текущая версия изменена вручную "
                f"({latest.strftime(_LABEL_DATETIME_FMT)})"
            )
        return "Текущая версия изменена вручную"

    if cur.last_action == "restore":
        try:
            created = datetime.fromisoformat(
                state.created_at,
            )
        except (ValueError, TypeError):
            created = None
        if created is not None:
            return (
                f"Текущая версия файлов от "
                f"{created.strftime(_LABEL_DATETIME_FMT)} "
                f"(восстановлена резервная копия)"
            )
        return "Текущая версия — восстановленная копия"

    try:
        act = datetime.fromisoformat(cur.last_action_at)
    except (ValueError, TypeError):
        act = None
    if act is not None:
        return (
            f"Текущая версия файлов от "
            f"{act.strftime(_LABEL_DATETIME_FMT)}"
        )
    return "Версия не определена"


# --- Один проход: сравнение с state + latest mtime ---

def _scan_vs_state(
    destination: str, state: StateData,
) -> tuple[bool, datetime | None]:
    """Один проход по destination.

    Возвращает (edited, latest_mtime). После первого
    обнаруженного отличия сравнение mtime прекращается, но
    обход продолжается — чтобы собрать latest для метки.
    """
    state_map: dict[str, StateFile] = {
        _norm(f.path): f for f in state.files
    }
    latest_ns = 0
    edited = False

    try:
        for root, dirs, names in os.walk(destination):
            rel_root = os.path.relpath(root, destination)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]
            for name in names:
                full = os.path.join(root, name)
                rel = _norm(
                    os.path.relpath(full, destination)
                )
                first = rel.split("/", 1)[0]
                if is_special_first_segment(first):
                    continue
                try:
                    st = os.stat(full)
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

                try:
                    expected_ns = int(
                        datetime.fromisoformat(
                            sf.mtime,
                        ).timestamp() * 1_000_000_000
                    )
                except (ValueError, TypeError, OSError):
                    continue

                if (
                    abs(st.st_mtime_ns - expected_ns)
                    > _MTIME_TOLERANCE_NS
                ):
                    edited = True
    except OSError as exc:
        logger.debug("_scan_vs_state: %r", exc)
        return True, _latest_file_mtime(destination)

    # Файлы state, которых нет в destination.
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


# --- Fallback: mtime самого свежего файла ---

def _latest_file_mtime(
    destination: str,
) -> datetime | None:
    """mtime самого свежего user-файла в destination."""
    base = Path(destination)
    if not base.is_dir():
        return None

    latest_ns = 0
    try:
        for root, dirs, files in os.walk(destination):
            rel_root = os.path.relpath(root, destination)
            if rel_root == ".":
                dirs[:] = [
                    d for d in dirs
                    if not is_special_first_segment(d)
                ]
            for name in files:
                rel = os.path.relpath(
                    os.path.join(root, name), destination,
                )
                first = rel.split(os.sep, 1)[0]
                if is_special_first_segment(first):
                    continue
                try:
                    st = os.stat(
                        os.path.join(root, name),
                    )
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
