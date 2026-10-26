"""Открытие файла программой по умолчанию с fallback-цепочкой.

`os.startfile` использует ассоциацию Windows: если пользователь
переназначил `.txt` на Notepad++, откроется он. Штатно ничего
не меняем.

Проблемы, которые ловим (все — синхронные `OSError`):

  • файл удалён / перемещён;
  • `.txt` ни с чем не ассоциирован (WinError 1155);
  • ассоциация битая: путь к программе в реестре не существует
    (WinError 2 / FileNotFoundError);
  • нет прав / файл занят.

Fallback-порядок:

  1. `os.startfile(display)` — ассоциация пользователя.
  2. `notepad.exe <path>` — Блокнот есть на любой Windows.
  3. `explorer /select,<path>` — открыть папку с выделением.
  4. Всё упало — возвращаем `success=False` с текстом для UI.

Что **не** ловится: ассоциация запустила процесс, но тот сразу
упал. `ShellExecute` не ждёт завершения — для нас «запуск
успешен». Ловить это ожиданием процесса — 0.5–2 сек задержки
в 99% успешных случаев; не делаем.

Длинные пути: `os.startfile`, `notepad.exe` и `explorer` не
понимают `\\?\\`. Для проверки существования используем
`long_io.isfile` (с префиксом), для запуска — `display_path`
(без префикса). Это ограничение ОС, не приложения.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from core import long_io
from core.paths import display_path, to_long_path
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = ["OpenFileResult", "open_file_with_fallback"]


# Способ, которым файл удалось открыть.
METHOD_ASSOC = "assoc"
METHOD_NOTEPAD = "notepad"
METHOD_EXPLORER = "explorer"
METHOD_NONE = ""


@dataclass
class OpenFileResult:
    """Результат попытки открыть файл."""

    success: bool
    method: str = METHOD_NONE
    error: str = ""


def open_file_with_fallback(path: str) -> OpenFileResult:
    """Открывает файл, перебирая способы до первого успешного.

    Args:
        path: Путь к файлу (может быть длинным).

    Returns:
        `OpenFileResult`: успех и способ, либо текст ошибки.
    """
    if not path:
        return OpenFileResult(
            success=False,
            error="Путь к файлу не задан",
        )

    if not long_io.isfile(to_long_path(path)):
        return OpenFileResult(
            success=False,
            error=f"Файл не найден:\n{path}",
        )

    display = display_path(path)

    # 1. Ассоциация пользователя: Блокнот, Notepad++, что угодно.
    try:
        os.startfile(display)  # type: ignore[attr-defined]
        return OpenFileResult(
            success=True, method=METHOD_ASSOC,
        )
    except AttributeError as exc:
        logger.debug("os.startfile недоступен: %r", exc)
    except OSError as exc:
        logger.warning(
            "os.startfile(%r) упал: %r", display, exc,
        )

    # 2. Блокнот — есть на любой Windows.
    try:
        subprocess.Popen(
            ["notepad.exe", display], close_fds=True,
        )
        return OpenFileResult(
            success=True, method=METHOD_NOTEPAD,
        )
    except (OSError, FileNotFoundError) as exc:
        logger.warning(
            "notepad.exe %r не запустился: %r", display, exc,
        )

    # 3. Проводник с выделением файла.
    try:
        subprocess.Popen(
            ["explorer", f"/select,{display}"],
            close_fds=True,
        )
        return OpenFileResult(
            success=True, method=METHOD_EXPLORER,
        )
    except OSError as exc:
        logger.warning(
            "explorer /select не запустился: %r", exc,
        )

    return OpenFileResult(
        success=False,
        error=(
            "Не удалось открыть файл ни программой по "
            "умолчанию, ни Блокнотом, ни Проводником.\n\n"
            f"Путь:\n{path}"
        ),
    )
