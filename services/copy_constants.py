"""Служебные имена, используемые модулями копирования."""

from __future__ import annotations

CCRUN_DIR_NAME = "!CCRun"
BACKUP_PREFIX = "!Backup_"
MANIFEST_FILENAME = "manifest.json"
MANIFEST_SCHEMA = 1

HASH_CACHE_FILENAME = "hashes.json"
HASH_CACHE_VERSION = 1

TMP_SUFFIX = ".tmp"


def is_special_first_segment(name: str) -> bool:
    if not name:
        return False
    if name == CCRUN_DIR_NAME:
        return True
    if name.startswith(BACKUP_PREFIX):
        return True
    return False
