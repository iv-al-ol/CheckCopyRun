"""Счётчики файлов и папок в destination.

Используется для фиксации состояния destination на момент
создания резервной копии — чтобы в UI можно было показать
«в проекте было N файлов, M папок» рядом с фактическим
содержимым бэкапа.

Служебные папки !CCRun и !Backup_* (на первом уровне) не
учитываются — они не часть «проекта».
"""

from __future__ import annotations

import os
from pathlib import Path

from services.copy_constants import is_special_first_segment
from utils.logger import get_logger

logger = get_logger(__name__)


def scan(destination: str) -> tuple[int, int]:
    """Считает (файлы, папки) в destination.

    Возвращает (files, dirs). При ошибке — (0, 0).
    Папки считаются без корневой destination.
    """
    if not destination:
        return 0, 0
    base = Path(destination)
    if not base.is_dir():
        return 0, 0

    files = 0
    dirs = 0
    try:
        for root, subdirs, names in os.walk(destination):
            rel_root = os.path.relpath(root, destination)
            if rel_root == ".":
                subdirs[:] = [
                    d for d in subdirs
                    if not is_special_first_segment(d)
                ]
            dirs += len(subdirs)
            files += len(names)
    except OSError as exc:
        logger.debug("scan %s: %r", destination, exc)
        return 0, 0

    return files, dirs
