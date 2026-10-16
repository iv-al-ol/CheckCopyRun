"""Доменные модели приложения."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Profile:
    """Один профиль копирования/запуска."""

    id: str = field(default_factory=_new_id)

    # Имя: хранится тремя полями, чтобы поддержать приоритет ручного.
    name_base: str = ""
    name_manual: str = ""
    name_auto: bool = True

    # Иконка: эмодзи или абсолютный путь к файлу.
    # icon_auto=True — иконка автоматически берётся из exe профиля,
    # пока пользователь не выбрал что-то вручную.
    icon: str = "📁"
    icon_auto: bool = True

    source: str = ""
    destination: str = ""

    # Путь к exe, относительный ИСХОДНОЙ директории.
    # В source файл лежит до копирования, в destination появляется
    # после копирования по тому же относительному пути.
    exe_relative: str = ""

    create_backup: bool = True
    run_after_copy: bool = False

    # --- Имя ---

    @property
    def display_name(self) -> str:
        if not self.name_auto:
            return self.name_manual or self.name_base
        suffix = self._auto_name_suffix()
        if suffix:
            return f"{self.name_base}: {suffix}"
        return self.name_base

    def _auto_name_suffix(self) -> str:
        # Приоритет: имя exe, потом имя папки-источника.
        if self.exe_relative:
            return os.path.basename(self.exe_relative)
        if self.source:
            base = os.path.basename(self.source.rstrip("/\\"))
            if base:
                return base
        return ""

    # --- Пути ---

    def exe_source_path(self) -> str:
        """Путь к exe в исходной директории. Отсюда файл копируется."""
        if not (self.exe_relative and self.source):
            return ""
        return os.path.join(self.source, self.exe_relative)

    def exe_full_path(self) -> str:
        """Путь к exe в целевой директории. Отсюда запускаем."""
        if not (self.exe_relative and self.destination):
            return ""
        return os.path.join(self.destination, self.exe_relative)

    # --- Проверки ---

    def has_source_and_dest(self) -> bool:
        if not (self.source and self.destination):
            return False
        return os.path.isdir(self.source) and os.path.isdir(self.destination)

    def has_exe_in_source(self) -> bool:
        path = self.exe_source_path()
        return bool(path) and os.path.isfile(path)

    def has_exe_in_destination(self) -> bool:
        path = self.exe_full_path()
        return bool(path) and os.path.isfile(path)

    def has_exe(self) -> bool:
        """Exe выбран и найден в источнике."""
        return self.has_exe_in_source()

    def can_run(self) -> bool:
        """Запуск возможен, только если exe уже скопирован в destination."""
        return (
            self.has_source_and_dest()
            and self.has_exe_in_destination()
        )


@dataclass
class AppSettings:
    """Все настройки приложения, сериализуются в settings.dat."""

    version: int = 1
    theme: str = "dark"
    confirm_on_exit: bool = False
    window_geometry: str = ""
    last_view: str = "main"
    profiles: list[Profile] = field(default_factory=list)
