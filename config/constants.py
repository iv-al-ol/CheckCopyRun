"""Общепроектные константы."""

from __future__ import annotations

# --- Приложение ---

APP_NAME = "CheckCopyRun"
APP_TITLE = "Check, Copy & Run"
APP_VERSION = "2.0.0"


# --- Логи ---

LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_MAX_SIZE_BYTES = 2 * 1024 * 1024
LOG_BACKUP_FILES = 3

LOG_DIR_NAME = "log"
LOG_FILE_NAME = "app.log"


# --- Настройки ---

SETTINGS_VERSION = 1
SETTINGS_DIR_NAME = APP_NAME
SETTINGS_FILE_NAME = "settings.dat"

ICONS_DIR_NAME = "icons"


# --- UI ---

THEME_DEFAULT = "dark"

WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 560

SIDEBAR_WIDTH = 260


# --- Профили ---

DEFAULT_PROFILE_NAME_PREFIX = "Профиль"
DEFAULT_PROFILE_ICON = "📁"


# --- Кэш хэшей для сравнения файлов ---
# Ускоряет повторные копирования: файлы сравниваются по размеру
# и mtime, хэш пересчитывается только когда что-то изменилось.
# Пользователь может отключить через настройки приложения —
# тогда используется побайтовое filecmp.cmp(shallow=False).

HASH_CACHE_ENABLED_DEFAULT = True
HASH_CACHE_ALGORITHM = "sha256"   # sha256 | sha1 | blake2b


# --- Разделитель ---

SEPARATOR_HEIGHT = 1
SEPARATOR_PADY = 8


# --- Нижняя зона окна ---

BOTTOM_AREA_HEIGHT = 72

SIDEBAR_ITEM_PADY_TOP = 3
SIDEBAR_ITEM_HEIGHT = 40
SIDEBAR_SETTINGS_PADY_BOTTOM = 12

PROFILE_BOTTOM_BUTTON_HEIGHT = 32
PROFILE_BOTTOM_BAR_PADY_TOP = 0
PROFILE_BOTTOM_BAR_PADY_BOTTOM = (
    BOTTOM_AREA_HEIGHT
    - 2 * SEPARATOR_PADY
    - SEPARATOR_HEIGHT
    - PROFILE_BOTTOM_BUTTON_HEIGHT
    - PROFILE_BOTTOM_BAR_PADY_TOP
)
