"""Настройка логирования.

Логи пишутся в Documents/CheckCopyRun/log/app.log с ротацией.
Путь до Documents вычисляется через core.paths (WinAPI
SHGetKnownFolderPath), чтобы корректно работать с перенесённой
папкой Documents (например, в OneDrive).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.constants import (
    LOG_BACKUP_FILES,
    LOG_DATE_FORMAT,
    LOG_DIR_NAME,
    LOG_FILE_NAME,
    LOG_FORMAT,
    LOG_LEVEL,
    LOG_MAX_SIZE_BYTES,
    SETTINGS_DIR_NAME,
)

_configured = False


def _resolve_level(level: str) -> int:
    if level.upper() == "OFF":
        return logging.CRITICAL + 100   # выше всего — глушим всё
    return getattr(logging, level.upper(), logging.INFO)


def _resolve_log_dir() -> Path | None:
    """Documents/CheckCopyRun/log. Импорт core.paths — ленивый."""
    try:
        from core.paths import get_documents_dir
    except Exception:
        # На этапе ранней инициализации core.paths может быть ещё
        # недоступен. Логирование в этом случае отключается — писать
        # об ошибке некуда.
        logging.disable(logging.CRITICAL)
        return None

    try:
        return get_documents_dir() / SETTINGS_DIR_NAME / LOG_DIR_NAME
    except Exception:
        logging.disable(logging.CRITICAL)
        return None


def setup_logging() -> None:
    """Инициализирует корневой logger. Вызывается один раз из main.py."""
    global _configured
    if _configured:
        return
    _configured = True

    level = _resolve_level(LOG_LEVEL)
    if level > logging.CRITICAL:
        logging.disable(logging.CRITICAL)
        return

    log_dir = _resolve_log_dir()
    if log_dir is None:
        return

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logging.disable(logging.CRITICAL)
        return

    handler = RotatingFileHandler(
        log_dir / LOG_FILE_NAME,
        maxBytes=LOG_MAX_SIZE_BYTES,
        backupCount=LOG_BACKUP_FILES,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
