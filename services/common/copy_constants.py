"""Служебные имена и константы CheckCopyRun.

Формат CAS:
  !CCRun/
    blobs/         — уникальные контенты по sha256
    states/        — JSON-снимки состояний
    hashes.json    — кэш хэшей src↔dst
    current.json   — указатель на текущее состояние
    restore_state.json — (устарело, не используется)

Старые !Backup_* папки в destination — от формата до CAS.
Не удаляются, не сканируются, но и не мешают: `is_special_first_segment`
их пропускает.
"""

from __future__ import annotations

# --- Служебная папка ---

CCRUN_DIR_NAME = "!CCRun"

# --- Сообщение от автора источника (внутри !CCRun) ---

MESSAGE_FILE_NAME = "message.txt"

# --- Старые артефакты (до CAS) ---

BACKUP_PREFIX = "!Backup_"

# --- Общие ---

TMP_SUFFIX = ".tmp"

# --- CAS: содержимое по хэшу ---

BLOBS_DIR_NAME = "blobs"
BLOB_HASH_ALGORITHM = "sha256"
BLOB_SUBDIR_LEN = 2
BLOB_CHUNK_SIZE = 1024 * 1024   # 1 МБ

# --- CAS: состояния ---

STATES_DIR_NAME = "states"
STATE_VERSION = 1
STATE_FILE_PREFIX = "state_"

STATE_KIND_AUTO = "auto"
STATE_KIND_RESTORE_POINT = "restore_point"

# --- Кэш хэшей ---

HASH_CACHE_FILENAME = "hashes.json"
HASH_CACHE_VERSION = 1

# --- Указатель на текущее состояние ---

CURRENT_FILENAME = "current.json"
CURRENT_VERSION = 1


def is_special_first_segment(name: str) -> bool:
    """True для служебных имён в корне destination.

    !CCRun — текущая служебная папка.
    !Backup_* — устаревший формат (до CAS). Не трогаем,
    но и не сканируем — защита от старых артефактов.

    Проверяется только первый сегмент относительного пути.
    В подпапках такие имена — обычные пользовательские.
    """
    if not name:
        return False
    if name == CCRUN_DIR_NAME:
        return True
    if name.startswith(BACKUP_PREFIX):
        return True
    return False
