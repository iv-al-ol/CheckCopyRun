"""Хранилище состояний destination.

Каждое состояние — JSON-файл в <destination>/!CCRun/states/:
  state_<YYYY.MM.DD_HH.MM.SS.mmm>.json

Поддержка длинных путей Windows: все I/O через long_io.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core import long_io
from core.paths import to_long_path
from services.common.copy_constants import (
    CCRUN_DIR_NAME,
    STATE_FILE_PREFIX,
    STATE_VERSION,
    STATES_DIR_NAME,
    TMP_SUFFIX,
)
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = [
    "StateData",
    "StateFile",
    "StateInfo",
    "StateStore",
    "StateStoreError",
    "now_iso",
]


class StateStoreError(RuntimeError):
    """Ошибка хранилища состояний."""


_STATE_RE = re.compile(
    r"^state_"
    r"(\d{4})\.(\d{2})\.(\d{2})_"
    r"(\d{2})\.(\d{2})\.(\d{2})\.(\d{3})"
    r"(?:_(\d+))?"
    r"\.json$"
)


def now_iso() -> str:
    """Текущее время в ISO 8601 с миллисекундами."""
    return datetime.now().isoformat(timespec="milliseconds")


# --- Модели ---

@dataclass
class StateFile:
    path: str
    sha256: str
    size: int
    mtime: str


@dataclass
class StateData:
    version: int = STATE_VERSION
    created_at: str = ""
    kind: str = ""
    source: str = ""
    files: list[StateFile] = field(default_factory=list)
    empty_dirs: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


@dataclass
class StateInfo:
    """Состояние + метаданные о его файле."""

    path: Path
    name: str
    timestamp: datetime | None
    data: StateData

    @property
    def kind(self) -> str:
        return self.data.kind

    @property
    def created_at(self) -> str:
        return self.data.created_at

    @property
    def files_count(self) -> int:
        return int(
            (self.data.summary or {}).get("files_count", 0) or 0
        )

    @property
    def empty_dirs_count(self) -> int:
        return int(
            (self.data.summary or {}).get(
                "empty_dirs_count", 0,
            ) or 0
        )

    @property
    def total_size(self) -> int:
        return int(
            (self.data.summary or {}).get("total_size", 0) or 0
        )

    @property
    def new_blobs_count(self) -> int:
        return int(
            (self.data.summary or {}).get(
                "new_blobs_count", 0,
            ) or 0
        )

    @property
    def new_blobs_bytes(self) -> int:
        return int(
            (self.data.summary or {}).get(
                "new_blobs_bytes", 0,
            ) or 0
        )


# --- Хранилище ---

class StateStore:
    """Управляет state-файлами одного destination."""

    def __init__(self, destination: str | Path):
        raw = (
            Path(destination) / CCRUN_DIR_NAME / STATES_DIR_NAME
        )
        self._root = Path(to_long_path(str(raw)))
        try:
            long_io.makedirs(str(self._root), exist_ok=True)
        except OSError as exc:
            raise StateStoreError(
                f"Не удалось создать {self._root}: {exc}"
            ) from exc

    @property
    def root(self) -> Path:
        return self._root

    # --- Создание ---

    def create(self, data: StateData) -> Path:
        """Записывает новое состояние. Возвращает путь к файлу."""
        if not data.created_at:
            data.created_at = now_iso()
        if not data.version:
            data.version = STATE_VERSION

        name = self._next_name()
        path = self._root / name
        payload = _to_payload(data)

        tmp = str(path) + TMP_SUFFIX
        try:
            with long_io.open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            long_io.replace(tmp, str(path))
        except OSError as exc:
            _safe_unlink(tmp)
            raise StateStoreError(
                f"Не удалось записать {path}: {exc}"
            ) from exc

        logger.debug(
            "Создано состояние %s (files=%d)",
            name, data.summary.get("files_count", 0),
        )
        return path

    # --- Чтение ---

    def load(self, ref: str | Path) -> StateData:
        """Загружает полные данные состояния по пути или имени."""
        path = self._resolve(ref)
        if not long_io.isfile(str(path)):
            raise StateStoreError(
                f"Файл состояния не найден: {path}"
            )
        try:
            with long_io.open(str(path), "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            raise StateStoreError(
                f"Не удалось прочитать {path}: {exc}"
            ) from exc
        return _from_payload(payload)

    def list(self) -> list[StateInfo]:
        """Все состояния, свежие сначала."""
        result: list[StateInfo] = []
        try:
            entries = list(long_io.scandir(str(self._root)))
        except OSError as exc:
            logger.warning(
                "Не удалось прочитать %s: %r", self._root, exc,
            )
            return []

        for entry in entries:
            if not entry.is_file():
                continue
            if entry.name.endswith(TMP_SUFFIX):
                continue
            m = _STATE_RE.match(entry.name)
            if not m:
                continue

            ts = _timestamp_from_match(m)
            try:
                data = self.load(entry.name)
            except StateStoreError as exc:
                logger.warning(
                    "Пропущено состояние %s: %r",
                    entry.name, exc,
                )
                continue

            result.append(StateInfo(
                path=Path(entry.path),
                name=Path(entry.name).stem,
                timestamp=ts,
                data=data,
            ))

        result.sort(
            key=lambda i: (
                i.timestamp or datetime.min
            ),
            reverse=True,
        )
        return result

    def latest(self) -> StateInfo | None:
        lst = self.list()
        return lst[0] if lst else None

    def get_by_name(self, name: str) -> StateInfo | None:
        if not name:
            return None
        if not name.endswith(".json"):
            name = name + ".json"
        for info in self.list():
            if info.path.name == name:
                return info
        return None

    # --- Удаление ---

    def delete(self, ref: str | Path) -> bool:
        path = self._resolve(ref)
        if not long_io.isfile(str(path)):
            return False
        try:
            long_io.remove(str(path))
            logger.debug("Удалено состояние: %s", path.name)
            return True
        except OSError as exc:
            logger.warning(
                "Не удалось удалить %s: %r", path, exc,
            )
            return False

    # --- Вспомогательное ---

    def _next_name(self) -> str:
        now = datetime.now()
        base = now.strftime("%Y.%m.%d_%H.%M.%S")
        ms = now.microsecond // 1000
        stem = f"{STATE_FILE_PREFIX}{base}.{ms:03d}"
        name = f"{stem}.json"
        if not long_io.exists(str(self._root / name)):
            return name
        for i in range(1, 10_000):
            alt = f"{stem}_{i}.json"
            if not long_io.exists(str(self._root / alt)):
                return alt
        raise StateStoreError(
            "Не удалось подобрать имя для состояния"
        )

    def _resolve(self, ref: str | Path) -> Path:
        p = Path(ref)
        if p.is_absolute():
            return p
        return self._root / p


# --- Сериализация ---

def _to_payload(data: StateData) -> dict:
    return {
        "version": data.version,
        "created_at": data.created_at,
        "kind": data.kind,
        "source": data.source,
        "files": [
            {
                "path": f.path,
                "sha256": f.sha256,
                "size": f.size,
                "mtime": f.mtime,
            }
            for f in data.files
        ],
        "empty_dirs": list(data.empty_dirs),
        "summary": dict(data.summary),
    }


def _from_payload(payload: dict) -> StateData:
    if not isinstance(payload, dict):
        raise StateStoreError("Некорректный формат состояния")

    version = int(payload.get("version", 0) or 0)
    if version > STATE_VERSION:
        raise StateStoreError(
            f"Состояние новее поддерживаемой версии: "
            f"{version} > {STATE_VERSION}"
        )

    files_raw = payload.get("files") or []
    files: list[StateFile] = []
    for item in files_raw:
        if not isinstance(item, dict):
            continue
        p = item.get("path")
        if not p or not isinstance(p, str):
            continue
        try:
            size = int(item.get("size", 0) or 0)
        except (TypeError, ValueError):
            size = 0
        files.append(StateFile(
            path=p,
            sha256=str(item.get("sha256", "") or ""),
            size=size,
            mtime=str(item.get("mtime", "") or ""),
        ))

    empty_raw = payload.get("empty_dirs") or []
    empty_dirs = [
        str(x) for x in empty_raw if isinstance(x, str)
    ]

    summary = payload.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}

    return StateData(
        version=version or STATE_VERSION,
        created_at=str(payload.get("created_at", "") or ""),
        kind=str(payload.get("kind", "") or ""),
        source=str(payload.get("source", "") or ""),
        files=files,
        empty_dirs=empty_dirs,
        summary=dict(summary),
    )


def _timestamp_from_match(m: re.Match) -> datetime | None:
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            int(m.group(7)) * 1000,
        )
    except ValueError as exc:
        logger.debug(
            "Не разобрано имя состояния %r: %r", m.group(0), exc,
        )
        return None


def _safe_unlink(path: str) -> None:
    try:
        if long_io.exists(path):
            long_io.remove(path)
    except OSError:
        pass
