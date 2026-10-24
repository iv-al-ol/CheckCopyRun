"""Общепроектные константы.

Именование (согласовано):
  • APP_NAME  — как приложение называется в UI.
  • APP_TITLE — заголовок окна.
  • Имя .exe и папки сборки — CCRun (см. build.py).
  • Служебная папка в destination — !CCRun (внутреннее,
    не путать с именем exe).
"""

from __future__ import annotations

# --- Приложение ---

# Имя приложения. Используется везде, где пользователь видит
# название: заголовки диалогов, About-вкладка, лог-файлы.
APP_NAME = "CheckCopyRun"

# Заголовок главного окна. Полная форма, с амперсандом.
APP_TITLE = "Check, Copy & Run"

# Версия. Источник истины для build.py и About.
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


# --- Кэш хэшей ---
HASH_CACHE_ENABLED_DEFAULT = True
HASH_CACHE_ALGORITHM = "sha256"


# --- Разделитель ---
SEPARATOR_HEIGHT = 1
SEPARATOR_PADY = 8


# --- Нижняя зона профиля: два ряда кнопок ---
# Ряд действий: Копировать / Запустить приложение / Резервные копии
PROFILE_ACTION_BUTTON_HEIGHT = 32
PROFILE_ACTION_BAR_PADY_TOP = 0
PROFILE_ACTION_BAR_PADY_BOTTOM = 8

# Ряд служебных: Сменить иконку / Переименовать / Сбросить / Удалить
PROFILE_UTILITY_BUTTON_HEIGHT = 32
PROFILE_UTILITY_BAR_PADY_TOP = 0
PROFILE_UTILITY_BAR_PADY_BOTTOM = 12


# --- Сайдбар: пункты ---
SIDEBAR_ITEM_PADY_TOP = 3
SIDEBAR_ITEM_HEIGHT = 40
SIDEBAR_SETTINGS_PADY_BOTTOM = 12
