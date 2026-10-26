"""Общепроектные константы.

Именование (согласовано):
  • APP_NAME  — как приложение называется в UI.
  • APP_TITLE — заголовок окна.
  • Имя .exe — CCRun, папки сборки — CheckCopyRun (см. build.py).
  • Служебная папка в destination — !CCRun (внутреннее,
    не путать с именем exe).
"""

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

# Тема по умолчанию — системная. Новый пользователь не
# удивится: приложение следует оформлению Windows. Сменить
# можно в «Настройки → Общие».
THEME_DEFAULT = "system"

# Минимальный размер: меньше пользователь не сможет ужать окно
# (на маленьком экране клампится по рабочей области).
WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 560

# Стартовый размер при первом запуске или без сохранённой
# геометрии. Подобран так, чтобы форма профиля со всеми
# примечаниями помещалась без полосы прокрутки. Клампится
# по рабочей области монитора.
WINDOW_DEFAULT_WIDTH = 900
WINDOW_DEFAULT_HEIGHT = 720

SIDEBAR_WIDTH = 260


# --- Профили ---
DEFAULT_PROFILE_NAME_PREFIX = "Профиль"
DEFAULT_PROFILE_ICON = "📁"


# --- Уведомления и мониторинг источника ---

MONITOR_DIR_NAME = "monitor"

MONITOR_INTERVAL_MIN = 1
MONITOR_INTERVAL_MAX = 60
MONITOR_INTERVAL_DEFAULT = 5

MONITOR_INDEX_MAX_FILES = 5000

MESSAGE_FILE_MAX_BYTES = 64 * 1024
MESSAGE_PREVIEW_LINES = 4
MESSAGE_PREVIEW_CHARS = 240

# Автоматическое скрытие уведомления (секунды).
# 0 — уведомление остаётся, пока его не закроют. Так
# пользователь не пропустит событие, пока нет маркера
# непрочитанных.
NOTIFY_AUTO_CLOSE_MIN = 0
NOTIFY_AUTO_CLOSE_MAX = 600
NOTIFY_AUTO_CLOSE_DEFAULT = NOTIFY_AUTO_CLOSE_MIN

NOTIFY_FADE_IN_MS = 180
NOTIFY_FADE_OUT_MS = 260
NOTIFY_FADE_STEP_MS = 16

NOTIFY_AGGREGATE_MAX_ITEMS = 5

NOTIFY_SPLIT_MAX_DETAILED = 3

NOTIFY_MAX_ACTIVE_TOASTS = 4


# --- Кэш хэшей ---
HASH_CACHE_ENABLED_DEFAULT = True
HASH_CACHE_ALGORITHM = "sha256"


# --- Разделитель ---
SEPARATOR_HEIGHT = 1
SEPARATOR_PADY = 0


# --- Нижняя зона профиля: два ряда кнопок ---
PROFILE_ROW_GAP = 8

PROFILE_ACTION_BUTTON_HEIGHT = 32
PROFILE_ACTION_BAR_PADY_TOP = PROFILE_ROW_GAP
PROFILE_ACTION_BAR_PADY_BOTTOM = PROFILE_ROW_GAP

PROFILE_UTILITY_BUTTON_HEIGHT = 32
PROFILE_UTILITY_BAR_PADY_TOP = PROFILE_ROW_GAP
PROFILE_UTILITY_BAR_PADY_BOTTOM = PROFILE_ROW_GAP


# --- Ширина кнопок в форме профиля ---

# Единая ширина всех кнопок в форме профиля:
#   • «Выбрать директорию», «Открыть папку», «Выбрать файл»,
#     «Создать message.txt» — всегда эта ширина;
#   • «Копировать», «Запустить приложение», «Резервные копии» —
#     всегда эта ширина (при минимальной ширине окна 3 кнопки
#     помещаются с запасом);
#   • «Сменить иконку», «Переименовать», «Сбросить настройки»,
#     «Удалить» — эта ширина, если окно растянуто достаточно;
#     при сжатии могут уменьшаться (минимум см. ниже).
PROFILE_FORM_BUTTON_WIDTH = 170

# Нижняя граница для служебных кнопок при сжатии окна.
PROFILE_UTILITY_BUTTON_MIN_WIDTH = 100


# --- Сайдбар: пункты ---
SIDEBAR_ITEM_PADY_TOP = 3
SIDEBAR_ITEM_HEIGHT = 40
SIDEBAR_SETTINGS_PADY_BOTTOM = 12
