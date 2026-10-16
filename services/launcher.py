"""Запуск .exe из целевой папки профиля.

Работает через subprocess.Popen со списком аргументов — путь с
пробелами не сломает запуск. cwd — папка exe, чтобы относительные
пути, которые использует запускаемая программа, разрешались от
неё.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)


class LaunchError(RuntimeError):
    """Ошибка запуска приложения."""


def launch_exe(path: str | os.PathLike) -> None:
    """Запускает exe. Бросает LaunchError при проблемах."""
    if not path:
        raise LaunchError("Путь к приложению не задан")

    p = Path(path)

    if not p.is_file():
        raise LaunchError(f"Файл не найден: {p}")

    if p.suffix.lower() != ".exe":
        raise LaunchError(f"Файл не является .exe: {p}")

    cwd = str(p.parent)

    try:
        subprocess.Popen(
            [str(p)],
            cwd=cwd,
            close_fds=True,
        )
    except OSError as exc:
        raise LaunchError(
            f"Не удалось запустить {p.name}: {exc}",
        ) from exc

    logger.info("Запущено приложение: %s", p)
