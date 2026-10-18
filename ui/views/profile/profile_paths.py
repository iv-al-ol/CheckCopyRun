"""Хелперы для работы с путями в профиле.

Чистая логика (пустота директорий, существование, пересоздание,
текст подписи) — без tkinter, легко тестируется.

Обёртки диалогов и открытия папок — с tkinter, но без знания
о виджетах профиля.

Конфликт путей — path_conflict_error — живёт в core.paths
(используется и copy_service, и UI-слоем).
"""

from __future__ import annotations

import os
import subprocess
from tkinter import filedialog

from core.models import Profile
from core.paths import path_conflict_error
from ui.dialogs import ask_yes_no, show_error
from utils.logger import get_logger

logger = get_logger(__name__)


# --- Чистая логика ---

def is_dir_empty(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            return next(it, None) is None
    except OSError as exc:
        logger.debug("scandir %s упал: %r", path, exc)
        return False


def ensure_directory(path: str) -> bool:
    """Гарантирует, что директория существует.

    Если её нет — создаёт (включая промежуточные). True при
    успехе, False если путь пуст или создать не удалось.
    """
    if not path:
        return False
    if os.path.isdir(path):
        return True
    try:
        os.makedirs(path, exist_ok=True)
        logger.info("Пересоздана директория: %s", path)
        return True
    except OSError as exc:
        logger.error("Не удалось создать %s: %r", path, exc)
        return False


def source_error(source: str) -> str | None:
    """Текст ошибки, если source не задан или не существует."""
    if not source:
        return "Исходная директория не задана."
    if not os.path.isdir(source):
        return (
            "Исходная директория не существует:\n"
            f"{source}\n\n"
            "Возможно, она была удалена или перемещена."
        )
    return None


def profile_subtitle(profile: Profile) -> str:
    """Текст подписи под именем профиля."""
    conflict = path_conflict_error(
        profile.source, profile.destination,
    )
    if conflict:
        return conflict

    parts = []

    if not profile.source:
        parts.append("Источник не задан")
    elif not os.path.isdir(profile.source):
        parts.append("Источник не существует")

    if not profile.destination:
        parts.append("Целевая директория не задана")

    if not profile.exe_relative:
        parts.append("Приложение не выбрано")
    elif not profile.has_exe_in_source():
        parts.append("Файл приложения не найден в источнике")
    elif not profile.has_exe_in_destination():
        parts.append("Приложение ещё не скопировано")

    return "  ·  ".join(parts) if parts else "Профиль готов"


# --- Диалоги выбора ---

def pick_source_directory(window, initial: str) -> str | None:
    initial_dir = initial if initial and os.path.isdir(initial) else None
    try:
        path = filedialog.askdirectory(
            parent=window,
            title="Выберите исходную директорию",
            initialdir=initial_dir,
            mustexist=True,
        )
    except Exception as exc:
        logger.error("askdirectory source: %r", exc)
        return None
    if not path:
        return None
    return os.path.abspath(path)


def pick_destination_directory(window, initial: str) -> str | None:
    initial_dir = initial if initial and os.path.isdir(initial) else None
    try:
        path = filedialog.askdirectory(
            parent=window,
            title="Выберите целевую директорию",
            initialdir=initial_dir,
            mustexist=True,
        )
    except Exception as exc:
        logger.error("askdirectory destination: %r", exc)
        return None
    if not path:
        return None
    return os.path.abspath(path)


def pick_exe_file(window, initial: str) -> str | None:
    initial_dir = initial if initial and os.path.isdir(initial) else None
    try:
        path = filedialog.askopenfilename(
            parent=window,
            title="Выберите запускаемое приложение",
            initialdir=initial_dir,
            filetypes=[("Программы", "*.exe"), ("Все файлы", "*.*")],
        )
    except Exception as exc:
        logger.error("askopenfilename exe: %r", exc)
        return None
    if not path:
        return None
    return os.path.abspath(path)


# --- Подпапка destination ---

def resolve_destination_target(
    window,
    source: str,
    abs_path: str,
) -> str | None:
    if not (source and os.path.isdir(source)):
        return abs_path

    source_name = os.path.basename(source.rstrip("/\\"))
    if not source_name:
        return abs_path

    last_segment = os.path.basename(abs_path.rstrip("/\\"))

    if last_segment.lower() == source_name.lower():
        return _handle_existing_target(window, abs_path, source_name)

    target = os.path.join(abs_path, source_name)

    if os.path.isdir(target):
        return _handle_existing_target(window, target, source_name)

    create = ask_yes_no(
        window,
        "Создать вложенную папку?",
        (
            f"Создать папку «{source_name}» внутри выбранной "
            f"директории?\n\n"
            f"Файлы будут скопированы в:\n{target}\n\n"
            f"Если выбрать «Нет», файлы попадут прямо в:\n"
            f"{abs_path}"
        ),
        yes_text="Да, создать",
        no_text="Нет, в корень",
        parent_visible=True,
    )

    if not create:
        return abs_path

    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        logger.error("Не удалось создать %s: %r", target, exc)
        show_error(
            window,
            "Не удалось создать папку",
            f"Путь: {target}\nОшибка: {exc}",
        )
        return None

    return target


def _handle_existing_target(
    window, target: str, source_name: str,
) -> str | None:
    if is_dir_empty(target):
        logger.debug(
            "Целевая папка %s существует, но пуста", target,
        )
        return target

    confirm = ask_yes_no(
        window,
        "Папка уже существует",
        (
            f"Папка «{source_name}» уже существует по пути:\n"
            f"{target}\n\n"
            f"Файлы внутри могут быть обновлены или "
            f"перезаписаны.\n"
            f"Изменённые файлы будут сохранены в резервную "
            f"копию (если эта опция включена в профиле).\n\n"
            f"Использовать эту папку для копирования?"
        ),
        yes_text="Да, использовать",
        no_text="Отмена",
        parent_visible=True,
    )

    if not confirm:
        return None
    return target


# --- Открытие в Проводнике ---

def open_folder_in_explorer(path: str) -> bool:
    if not path or not os.path.isdir(path):
        logger.debug("Папка не существует: %r", path)
        return False

    try:
        subprocess.Popen(["explorer", path])
    except OSError as exc:
        logger.error("Не удалось открыть папку %s: %r", path, exc)
        return False

    logger.debug("Открыта папка: %s", path)
    return True
