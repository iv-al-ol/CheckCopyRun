"""Общепроектные константы.

Правила именования:
  • <ОБЛАСТЬ>_<ЧТО>         — LOG_*, WINDOW_*, SETTINGS_*, BOTTOM_*
  • суффикс единицы          — _BYTES, _WIDTH, _HEIGHT, _COUNT, _PADY
  • множественное число      — для коллекций (_FILES)
  • строковые значения       — в нижнем регистре (log, icons, app.log)

Область отвечает на вопрос «о чём», объект — «что именно».
Например: LOG_DIR_NAME (имя директории логов), WINDOW_MIN_WIDTH
(минимальная ширина окна).
"""

from __future__ import annotations

# --- Приложение ---

APP_NAME = "CheckCopyRun"
APP_TITLE = "Check, Copy & Run"
APP_VERSION = "2.0.0"


# --- Логи ---
# Уровень: DEBUG / INFO / WARNING / ERROR / OFF.
# OFF полностью отключает запись в файл.

LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_MAX_SIZE_BYTES = 2 * 1024 * 1024   # 2 МБ
LOG_BACKUP_FILES = 3                   # текущий + 2 ротации

# Папка логов: Documents/CheckCopyRun/log
LOG_DIR_NAME = "log"
LOG_FILE_NAME = "app.log"


# --- Настройки ---

SETTINGS_VERSION = 1
SETTINGS_DIR_NAME = APP_NAME
SETTINGS_FILE_NAME = "settings.dat"

# Папка для извлечённых PNG-иконок: Documents/CheckCopyRun/icons
ICONS_DIR_NAME = "icons"


# --- UI ---

THEME_DEFAULT = "dark"           # "system" | "dark" | "light"

WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 560
WINDOW_DEFAULT_WIDTH = 1100
WINDOW_DEFAULT_HEIGHT = 680

SIDEBAR_WIDTH = 260


# --- Профили ---

DEFAULT_PROFILE_NAME_PREFIX = "Профиль"
DEFAULT_PROFILE_ICON = "📁"


# --- Разделитель ---
# Тонкая линия — tk.Frame(height=1). Не масштабируется CTk, поэтому
# ровно 1 физический пиксель при любом DPI. Цвет подбирается
# в рантайме под текущую тему (см. _separator_hex в модулях).

SEPARATOR_HEIGHT = 1
SEPARATOR_PADY = 8           # отступ сверху и снизу разделителя


# --- Нижняя зона окна ---
# Разделитель в сайдбаре и в профиле должен стоять на одной
# горизонтальной линии. Иначе при переключении разделов линия
# «прыгает» вверх-вниз — это заметно и выглядит неаккуратно.
#
# BOTTOM_AREA_HEIGHT — общая высота от верхнего края разделителя
# до низа окна. Все нижние отступы вычисляются так, чтобы эта
# сумма совпадала. Если меняется высота кнопок или отступы,
# достаточно поправить числа ниже — формула пересчитает остальное.

BOTTOM_AREA_HEIGHT = 72      # высота нижней зоны целиком, px

# Сайдбар: пункт «Настройки». Top-отступ используется и для
# остальных пунктов сайдбара — это вертикальный padding сверху.
SIDEBAR_ITEM_PADY_TOP = 3
SIDEBAR_ITEM_HEIGHT = 40
SIDEBAR_SETTINGS_PADY_BOTTOM = 12

# Профиль: ряд кнопок внизу. Высота кнопок — стандартная для
# StyledButton (32 px). Нижний отступ вычисляется из общей
# высоты зоны, чтобы разделители совпали с сайдбаром.
PROFILE_BOTTOM_BUTTON_HEIGHT = 32
PROFILE_BOTTOM_BAR_PADY_TOP = 0
PROFILE_BOTTOM_BAR_PADY_BOTTOM = (
    BOTTOM_AREA_HEIGHT
    - 2 * SEPARATOR_PADY
    - SEPARATOR_HEIGHT
    - PROFILE_BOTTOM_BUTTON_HEIGHT
    - PROFILE_BOTTOM_BAR_PADY_TOP
)
