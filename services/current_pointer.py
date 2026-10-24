"""Указатель на текущее состояние destination.

Файл: <destination>/!CCRun/current.json.

Содержимое:
  • version        — версия формата;
  • state          — имя state-файла (без пути), содержимое
                     которого совпадает с текущим destination;
  • last_action    — "copy" | "restore" | "initial";
  • last_action_at — ISO 8601 с миллисекундами, время завершения
                     последнего copy/restore;
  • restored_from  — при last_action="restore": имя state,
                     к которому восстановили.

Используется:
  • copy_service — чтобы понять, изменилось ли состояние
    с прошлого раза (не создавать лишних states);
  • restore_service — чтобы знать, что было до restore
    (для «точки возврата»);
  • UI — метка «Текущая версия файлов от …» и «Текущий» в
    списке состояний.

Файл маленький (~200 байт), пишется атомарно через .tmp.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from services.copy_constants import (
    CCRUN_DIR_NAME,
    CURRENT_FILENAME,
    CURRENT_VERSION,
    TMP_SUFFIX,
)
from services.state_store import now_iso
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = [
    "CurrentData",
    "CurrentPointer",
    "CurrentPointerError",
]


class CurrentPointerError(RuntimeError):
    """Ошибка чтения/записи current.json."""


@dataclass
class CurrentData:
    version: int = CURRENT_VERSION
    state: str = ""
    last_action: str = ""
    last_action_at: str = ""
    restored_from: str = ""


class CurrentPointer:
    """Управляет current.json для одного destination."""

    def __init__(self, destination: str | Path):
        self._root = Path(destination) / CCRUN_DIR_NAME
        self._path = self._root / CURRENT_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    # --- Чтение ---

    def load(self) -> CurrentData | None:
        if not self._path.is_file():
            return None
        try:
            raw = self._path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except Exception as exc:
            logger.warning(
                "Не удалось прочитать %s: %r",
                self._path, exc,
            )
            return None
        if not isinstance(payload, dict):
            return None
        return CurrentData(
            version=int(
                payload.get("version", 0) or 0,
            ),
            state=str(payload.get("state", "") or ""),
            last_action=str(
                payload.get("last_action", "") or "",
            ),
            last_action_at=str(
                payload.get("last_action_at", "") or "",
            ),
            restored_from=str(
                payload.get("restored_from", "") or "",
            ),
        )

    # --- Запись ---

    def save(self, data: CurrentData) -> None:
        if not data.last_action_at:
            data.last_action_at = now_iso()
        if not data.version:
            data.version = CURRENT_VERSION

        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CurrentPointerError(
                f"Не удалось создать {self._root}: {exc}"
            ) from exc

        tmp = str(self._path) + TMP_SUFFIX
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    asdict(data), f,
                    ensure_ascii=False, indent=2,
                )
            os.replace(tmp, str(self._path))
        except OSError as exc:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise CurrentPointerError(
                f"Не удалось записать {self._path}: {exc}"
            ) from exc

        logger.debug(
            "current.json: state=%r action=%r",
            data.state, data.last_action,
        )

    # --- Удобные обёртки ---

    def save_copy(self, state_name: str) -> None:
        self.save(CurrentData(
            state=state_name,
            last_action="copy",
            last_action_at=now_iso(),
        ))

    def save_restore(
        self,
        state_name: str,
        restored_from: str,
    ) -> None:
        self.save(CurrentData(
            state=state_name,
            last_action="restore",
            last_action_at=now_iso(),
            restored_from=restored_from,
        ))

    def save_initial(self, state_name: str) -> None:
        self.save(CurrentData(
            state=state_name,
            last_action="initial",
            last_action_at=now_iso(),
        ))
