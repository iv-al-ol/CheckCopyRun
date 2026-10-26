"""Запуск .exe из целевой папки профиля.

Работает через subprocess.Popen со списком аргументов — путь с
пробелами не сломает запуск. cwd — папка exe, чтобы относительные
пути, которые использует запускаемая программа, разрешались от
неё.

Длинные пути Windows (>260): проверка существования идёт через
`long_io.isfile` (понимает префикс `\\?\\`). Для запуска
используется трюк: `cwd=родительская_папка`, а в `args` —
только имя файла. `CreateProcessW` не понимает `\\?\\` в
`lpApplicationName`, но корректно разрешает имя относительно
`lpCurrentDirectory` (на Win10+ с манифестом `longPathAware=true`
это работает и для длинных путей). Если ОС всё же откажется —
пробрасываем LaunchError с понятным текстом.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from core import long_io
from core.paths import display_path, to_long_path
from utils.logger import get_logger

logger = get_logger(__name__)


class LaunchError(RuntimeError):
    """Ошибка запуска приложения."""


def launch_exe(path: str | os.PathLike) -> None:
    """Запускает exe. Бросает LaunchError при проблемах."""
    if not path:
        raise LaunchError("Путь к приложению не задан")

    p = Path(str(path))

    if p.suffix.lower() != ".exe":
        raise LaunchError(f"Файл не является .exe: {p}")

    # long_io.isfile понимает `\\?\`; os.path.isfile — нет.
    if not long_io.isfile(to_long_path(str(p))):
        raise LaunchError(f"Файл не найден: {p}")

    # CreateProcessW не принимает префикс `\\?\` в
    # lpApplicationName, но разрешает имя относительно
    # lpCurrentDirectory. Передаём имя файла и cwd отдельно —
    # для коротких путей работает так же, как раньше.
    abs_path = display_path(to_long_path(str(p)))
    abs_p = Path(abs_path)
    cwd = str(abs_p.parent)
    name = abs_p.name

    try:
        subprocess.Popen(
            [name],
            cwd=cwd,
            close_fds=True,
        )
    except OSError as exc:
        msg = str(exc).lower()
        if "too long" in msg or "filename or extension is too long" in msg:
            raise LaunchError(
                f"Не удалось запустить {name}: путь слишком "
                f"длинный для Windows. {exc}"
            ) from exc
        raise LaunchError(
            f"Не удалось запустить {name}: {exc}",
        ) from exc

    logger.info("Запущено приложение: %s", p)
