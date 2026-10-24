"""Реестр состояний destination.

Обёртка над StateStore с данными, удобными для UI:
  • метки «Текущий» / «Точка возврата»;
  • счётчики для строки списка;
  • удаление с защитой текущего состояния.

Формат строки для UI (используется в backup_list):
  • Заголовок:  <DD.MM.YYYY HH:MM:SS>  ·  [Текущий | Точка возврата]
  • Детали:     В проекте: N файлов, M папок (<size>)
                Сохранены изменения: X файлов (<bytes>)

Старый API (!Backup_* папки) удалён. Совместимость с ним не
поддерживается — согласовано с пользователем.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from services.current_pointer import CurrentData, CurrentPointer
from services.state_store import (
    StateInfo,
    StateStore,
    StateStoreError,
)
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = [
    "StateUiInfo",
    "compute_ui_info",
    "delete_state",
    "get_current",
    "list_states",
]


# --- Модели ---

@dataclass
class StateUiInfo:
    """StateInfo + UI-метки."""

    info: StateInfo
    is_current: bool
    is_restore_point: bool

    @property
    def name(self) -> str:
        return self.info.path.name


# --- Публичное API ---

def list_states(destination: str) -> list[StateInfo]:
    """Все состояния destination, свежие сначала.

    При ошибке инициализации — пустой список (не падаем).
    """
    if not destination:
        return []
    try:
        store = StateStore(destination)
    except StateStoreError as exc:
        logger.warning("list_states(%s): %r", destination, exc)
        return []
    return store.list()


def get_current(destination: str) -> CurrentData | None:
    if not destination:
        return None
    return CurrentPointer(destination).load()


def compute_ui_info(
    info: StateInfo, current: CurrentData | None,
) -> StateUiInfo:
    """Считает UI-метки для одного состояния."""
    is_current = (
        current is not None
        and current.state == info.path.name
    )
    is_restore_point = info.kind == "restore_point"
    return StateUiInfo(
        info=info,
        is_current=is_current,
        is_restore_point=is_restore_point,
    )


def delete_state(
    destination: str,
    state_ref: str | Path,
) -> tuple[bool, str]:
    """Удаляет состояние. Возвращает (ok, error_message).

    Запрещает удаление текущего состояния — иначе теряется
    указатель на «где мы сейчас». Пользователь должен сначала
    переключиться на другое состояние (restore), потом удалять.

    GC blob-ов НЕ выполняется — это отдельная операция
    (cleanup_states). Причина: удаление одного state может
    освободить blob-ы, но пересчёт keep-хэшей по всем остальным
    states — дорого, и делать его на каждое удаление не стоит.
    """
    if not destination:
        return False, "Не указана папка назначения"

    try:
        store = StateStore(destination)
    except StateStoreError as exc:
        return False, f"Хранилище недоступно: {exc}"

    # Защита текущего.
    current = CurrentPointer(destination).load()
    target = Path(state_ref)
    if not target.is_absolute():
        target_name = target.name
    else:
        target_name = target.name

    if (
        current is not None
        and current.state
        and current.state == target_name
    ):
        return False, (
            "Нельзя удалить текущее состояние. "
            "Сначала восстановите другое."
        )

    ok = store.delete(state_ref)
    if not ok:
        return False, f"Не удалось удалить состояние: {state_ref}"

    logger.info("Удалено состояние: %s", target_name)
    return True, ""


def collect_keep_hashes(
    destination: str,
    exclude: set[str] | None = None,
) -> set[str]:
    """Собирает все sha256 из всех state-файлов destination.

    Используется для GC blob-ов. exclude — имена state-файлов,
    которые нужно пропустить (например, удалённые, но ещё
    лежащие на диске).

    Ошибки чтения отдельных state-файлов игнорируются (state
    повреждён → его хэши не учитываются, но blob-ы таких
    файлов могут быть собраны GC — это допустимо, они
    не нужны для восстановления).
    """
    if not destination:
        return set()
    try:
        store = StateStore(destination)
    except StateStoreError as exc:
        logger.warning(
            "collect_keep_hashes: хранилище недоступно: %r", exc,
        )
        return set()

    skip = exclude or set()
    hashes: set[str] = set()
    for info in store.list():
        if info.path.name in skip:
            continue
        try:
            data = store.load(info.path.name)
        except StateStoreError as exc:
            logger.debug(
                "collect_keep_hashes: пропущено %s: %r",
                info.path.name, exc,
            )
            continue
        for f in data.files:
            if f.sha256:
                hashes.add(f.sha256)
    return hashes
