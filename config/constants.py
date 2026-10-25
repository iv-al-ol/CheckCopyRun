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


# --- Уведомления и мониторинг источника ---

# Папка с базовыми снимками мониторинга внутри Documents/CheckCopyRun.
MONITOR_DIR_NAME = "monitor"

# Границы интервала опроса источника (минуты).
MONITOR_INTERVAL_MIN = 1
MONITOR_INTERVAL_MAX = 60
MONITOR_INTERVAL_DEFAULT = 5

# Порог, после которого снимок хранится только агрегатом
# (файлов, байт, максимальный mtime) без посуточного индекса.
MONITOR_INDEX_MAX_FILES = 5000

# Сообщение от автора папки-источника (внутри !CCRun).
# Имя файла — services/common/copy_constants.MESSAGE_FILE_NAME.
MESSAGE_FILE_MAX_BYTES = 64 * 1024
MESSAGE_PREVIEW_LINES = 4
MESSAGE_PREVIEW_CHARS = 240

# Автоматическое скрытие уведомления (секунды).
# 0 — уведомление остаётся на экране, пока его не закроют.
NOTIFY_AUTO_CLOSE_MIN = 0
NOTIFY_AUTO_CLOSE_MAX = 600
NOTIFY_AUTO_CLOSE_DEFAULT = NOTIFY_AUTO_CLOSE_MIN

# Плавное появление/исчезновение всплывающего уведомления.
NOTIFY_FADE_IN_MS = 180
NOTIFY_FADE_OUT_MS = 260
NOTIFY_FADE_STEP_MS = 16

# Порог агрегации: больше профилей за цикл — одно уведомление списком.
NOTIFY_AGGREGATE_MAX_ITEMS = 5


# --- Кэш хэшей ---
HASH_CACHE_ENABLED_DEFAULT = True
HASH_CACHE_ALGORITHM = "sha256"


# --- Разделитель ---
# Отступ подобран так, чтобы форма профиля целиком помещалась
# в окно минимальной высоты без полосы прокрутки.
SEPARATOR_HEIGHT = 1
SEPARATOR_PADY = 0


# --- Нижняя зона профиля: два ряда кнопок ---
# Вертикальные отступы задаются ТОЛЬКО здесь, разделители
# рисуются вплотную (SEPARATOR_PADY = 0). Иначе зазор между
# разделителем и кнопкой складывается из двух источников и
# выглядит неравномерным.
PROFILE_ROW_GAP = 8

# Ряд действий: Копировать / Запустить приложение / Резервные копии
PROFILE_ACTION_BUTTON_HEIGHT = 32
PROFILE_ACTION_BAR_PADY_TOP = PROFILE_ROW_GAP
PROFILE_ACTION_BAR_PADY_BOTTOM = PROFILE_ROW_GAP

# Ряд служебных: Сменить иконку / Переименовать / Сбросить / Удалить
PROFILE_UTILITY_BUTTON_HEIGHT = 32
PROFILE_UTILITY_BAR_PADY_TOP = PROFILE_ROW_GAP
PROFILE_UTILITY_BAR_PADY_BOTTOM = PROFILE_ROW_GAP


# --- Сайдбар: пункты ---
SIDEBAR_ITEM_PADY_TOP = 3
SIDEBAR_ITEM_HEIGHT = 40
SIDEBAR_SETTINGS_PADY_BOTTOM = 12
