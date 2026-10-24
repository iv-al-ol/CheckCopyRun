"""Указатель на текущее состояние destination.

Файл: <destination>/!CCRun/current.json. Поддержка длинных
путей Windows: I/O через long_io.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from core import long_io
from core.paths import to_long_path
from services.cas.state_store import now_iso
from services.common.copy_constants import (
    CCRUN_DIR_NAME,
    CURRENT_FILENAME,
    CURRENT_VERSION,
    TMP_SUFFIX,
)
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
        raw = Path(destination) / CCRUN_DIR_NAME / CURRENT_FILENAME
        self._path = Path(to_long_path(str(raw)))

    @property
    def path(self) -> Path:
        return self._path

    # --- Чтение ---

    def load(self) -> CurrentData | None:
        if not long_io.isfile(str(self._path)):
            return None
        try:
            with long_io.open(
                str(self._path), "r", encoding="utf-8",
            ) as f:
                payload = json.load(f)
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
            long_io.makedirs(
                str(self._path.parent), exist_ok=True,
            )
        except OSError as exc:
            raise CurrentPointerError(
                f"Не удалось создать {self._path.parent}: {exc}"
            ) from exc

        tmp = str(self._path) + TMP_SUFFIX
        try:
            with long_io.open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    asdict(data), f,
                    ensure_ascii=False, indent=2,
                )
            long_io.replace(tmp, str(self._path))
        except OSError as exc:
            try:
                if long_io.exists(tmp):
                    long_io.remove(tmp)
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
