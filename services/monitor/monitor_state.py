"""Персистентная база мониторинга между запусками приложения.

Для каждого профиля хранится JSON-файл
`%USERPROFILE%/Documents/CheckCopyRun/monitor/<profile_id>.json`:

    {
      "version": 1,
      "profile_id": "…",
      "source": "C:/build",
      "snapshot": { … см. source_snapshot … },
      "message_sha256": "…",
      "saved_at": "2026-10-24T19:00:00"
    }

Запись атомарная (`.tmp` + `os.replace`), как и остальные файлы
`!CCRun`/`settings.dat` — промежуточное состояние не должно быть
видно другому процессу.

Первый запуск профиля = «нет базы»: уведомление не показывается,
чтобы не сообщать «изменилось всё». База создаётся молча.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from config.constants import MONITOR_DIR_NAME, SETTINGS_DIR_NAME
from core.paths import get_documents_dir
from services.common.time_utils import now_iso
from services.monitor.source_snapshot import (
    snapshot_from_dict,
    snapshot_to_dict,
)
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "MonitorEntry",
    "MonitorStore",
    "get_monitor_dir",
]

STATE_VERSION = 1

# profile_id — hex от uuid4, но защищаемся от подстановки в имя
# файла на случай ручной правки settings.dat.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def get_monitor_dir() -> Path:
    """Каталог базы мониторинга в Documents."""
    return get_documents_dir() / SETTINGS_DIR_NAME / MONITOR_DIR_NAME


@dataclass
class MonitorEntry:
    """Запись мониторинга одного профиля."""

    profile_id: str
    source: str = ""
    snapshot: dict | None = None
    message_sha256: str = ""
    saved_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION,
            "profile_id": self.profile_id,
            "source": self.source,
            "snapshot": (
                snapshot_to_dict(self.snapshot)
                if self.snapshot is not None
                else None
            ),
            "message_sha256": self.message_sha256,
            "saved_at": self.saved_at,
        }

    @classmethod
    def from_dict(
        cls, data: dict, *, profile_id: str,
    ) -> MonitorEntry:
        return cls(
            profile_id=str(data.get("profile_id") or profile_id),
            source=str(data.get("source") or ""),
            snapshot=snapshot_from_dict(data.get("snapshot")),
            message_sha256=str(data.get("message_sha256") or ""),
            saved_at=str(data.get("saved_at") or now_iso()),
        )


class MonitorStore:
    """Чтение и атомарная запись записей мониторинга."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = Path(base_dir) if base_dir else get_monitor_dir()

    @property
    def base_dir(self) -> Path:
        return self._base

    def path_for(self, profile_id: str) -> Path | None:
        """Путь к файлу записи. `None` для небезопасного id."""
        if not profile_id or not _SAFE_ID.match(profile_id):
            logger.warning(
                "MonitorStore: небезопасный profile_id %r", profile_id,
            )
            return None
        return self._base / f"{profile_id}.json"

    def load(self, profile_id: str) -> MonitorEntry | None:
        """Читает запись профиля. `None` — базы ещё нет."""
        path = self.path_for(profile_id)
        if path is None or not path.is_file():
            return None

        try:
            raw = path.read_bytes()
            data = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning(
                "MonitorStore: не удалось прочитать %s: %r", path, exc,
            )
            return None

        if not isinstance(data, dict):
            logger.warning("MonitorStore: %s — не объект", path)
            return None

        try:
            return MonitorEntry.from_dict(data, profile_id=profile_id)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "MonitorStore: некорректная запись %s: %r", path, exc,
            )
            return None

    def save(self, entry: MonitorEntry) -> bool:
        """Атомарно сохраняет запись.

        Returns:
            `True` при успешной записи.
        """
        path = self.path_for(entry.profile_id)
        if path is None:
            return False

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                entry.to_dict(), ensure_ascii=False, indent=2,
            ).encode("utf-8")
        except (OSError, TypeError, ValueError) as exc:
            logger.error(
                "MonitorStore: подготовка %s: %r", path, exc,
            )
            return False

        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".", suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            Path(tmp_name).replace(path)
        except OSError as exc:
            logger.error(
                "MonitorStore: запись %s: %r", path, exc,
            )
            self._cleanup(tmp_name)
            return False
        return True

    def clear(self, profile_id: str) -> None:
        """Удаляет запись профиля (профиль удалён / путь сменён)."""
        path = self.path_for(profile_id)
        if path is None or not path.is_file():
            return
        try:
            path.unlink()
        except OSError as exc:
            logger.debug(
                "MonitorStore: не удалось удалить %s: %r", path, exc,
            )

    def prune(self, keep_ids: set[str]) -> int:
        """Удаляет записи профилей, которых больше нет.

        Returns:
            Количество удалённых файлов.
        """
        if not self._base.is_dir():
            return 0

        removed = 0
        try:
            entries = list(self._base.glob("*.json"))
        except OSError as exc:
            logger.warning("MonitorStore.prune: %r", exc)
            return 0

        for path in entries:
            if path.stem in keep_ids:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                logger.debug(
                    "MonitorStore.prune: %s: %r", path, exc,
                )
        return removed

    @staticmethod
    def _cleanup(tmp_name: str) -> None:
        try:
            Path(tmp_name).unlink()
        except OSError as exc:
            logger.debug(
                "MonitorStore: не удалось удалить %s: %r",
                tmp_name, exc,
            )
