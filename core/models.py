"""Доменные модели приложения."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from config.constants import HASH_CACHE_ENABLED_DEFAULT


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Profile:
    """Один профиль копирования/запуска."""

    id: str = field(default_factory=_new_id)

    name_base: str = ""
    name_manual: str = ""
    name_auto: bool = True

    icon: str = "📁"
    icon_auto: bool = True

    source: str = ""
    destination: str = ""
    exe_relative: str = ""

    create_backup: bool = True
    create_backup_warned: bool = False

    run_after_copy: bool = False
    check_on_startup: bool = False

    mirror_mode: bool = False

    pinned: bool = False
    last_used_at: str = ""

    @property
    def display_name(self) -> str:
        if not self.name_auto:
            return self.name_manual or self.name_base
        suffix = self._auto_name_suffix()
        if suffix:
            return f"{self.name_base}: {suffix}"
        return self.name_base

    def _auto_name_suffix(self) -> str:
        if self.exe_relative:
            return os.path.basename(self.exe_relative)
        if self.source:
            base = os.path.basename(self.source.rstrip("/\\"))
            if base:
                return base
        return ""

    def exe_source_path(self) -> str:
        if not (self.exe_relative and self.source):
            return ""
        return os.path.join(self.source, self.exe_relative)

    def exe_full_path(self) -> str:
        if not (self.exe_relative and self.destination):
            return ""
        return os.path.join(self.destination, self.exe_relative)

    def has_source_and_dest(self) -> bool:
        if not (self.source and self.destination):
            return False
        return (
            os.path.isdir(self.source)
            and os.path.isdir(self.destination)
        )

    def can_copy(self) -> bool:
        if not self.source or not os.path.isdir(self.source):
            return False
        if not self.destination:
            return False
        return True

    def has_exe_in_source(self) -> bool:
        path = self.exe_source_path()
        return bool(path) and os.path.isfile(path)

    def has_exe_in_destination(self) -> bool:
        path = self.exe_full_path()
        return bool(path) and os.path.isfile(path)

    def has_exe(self) -> bool:
        return self.has_exe_in_source()

    def can_run(self) -> bool:
        return (
            self.has_source_and_dest()
            and self.has_exe_in_destination()
        )

    def touch(self) -> None:
        self.last_used_at = datetime.now().isoformat(
            timespec="seconds",
        )


@dataclass
class AppSettings:
    version: int = 1
    theme: str = "dark"
    confirm_on_exit: bool = False
    window_geometry: str = ""
    hash_cache_enabled: bool = HASH_CACHE_ENABLED_DEFAULT

    run_autocheck_on_restored: bool = False
    minimize_to_tray: bool = False
    autostart: bool = False
    start_minimized: bool = False

    backup_keep_last_enabled: bool = False
    backup_keep_last_n: int = 10
    backup_delete_older_enabled: bool = False
    backup_delete_older_days: int = 30

    profiles: list[Profile] = field(default_factory=list)
