"""Манифест бэкапа: !CCRun/manifest.json.

Создаётся в каждой папке !Backup_<stamp>/ и описывает, что было
бэкапнуто, откуда, когда и с каким результатом. Используется для
аудита и будущего отката вручную.

Запись атомарная: сначала в .tmp, затем os.replace.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config.constants import APP_NAME, APP_VERSION
from services.copy_constants import (
    CCRUN_DIR_NAME,
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA,
    TMP_SUFFIX,
)
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ManifestEntry:
    """Одна запись манифеста — файл, который был заменён."""

    path: str
    size: int
    mtime: str
    action: str = "replaced"


def iso_mtime(path: str) -> str:
    """mtime файла в ISO 8601 с миллисекундами. '' при ошибке."""
    try:
        ts = os.path.getmtime(path)
    except OSError as exc:
        logger.debug("mtime %s: %r", path, exc)
        return ""
    try:
        return datetime.fromtimestamp(ts).isoformat(
            timespec="milliseconds",
        )
    except Exception as exc:
        logger.debug("iso mtime %s: %r", path, exc)
        return ""


def write_manifest(
    backup_dir: Path,
    *,
    source: str,
    destination: str,
    files: list[ManifestEntry],
    summary: dict[str, Any],
    schema: int = MANIFEST_SCHEMA,
) -> None:
    """Атомарно пишет манифест в backup_dir/!CCRun/manifest.json."""
    payload = {
        "schema": schema,
        "created_at": datetime.now().isoformat(
            timespec="milliseconds",
        ),
        "source": source,
        "destination": destination,
        "app": APP_NAME,
        "app_version": APP_VERSION,
        "files": [
            {
                "path": e.path,
                "size": e.size,
                "mtime": e.mtime,
                "action": e.action,
            }
            for e in files
        ],
        "summary": summary,
    }

    ccrun = backup_dir / CCRUN_DIR_NAME
    try:
        ccrun.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(
            "Не удалось создать %s: %r", ccrun, exc,
        )
        return

    target = ccrun / MANIFEST_FILENAME
    tmp = target.with_suffix(target.suffix + TMP_SUFFIX)

    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
        logger.debug("Манифест записан: %s", target)
    except Exception as exc:
        logger.error(
            "Не удалось записать манифест %s: %r", target, exc,
        )
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError as cleanup_exc:
            logger.debug(
                "cleanup манифеста %s: %r", tmp, cleanup_exc,
            )
