"""Действия над профилями: создание, переименование, иконка, удаление.

Выделено из MainWindow, чтобы он оставался оркестратором, а не
монолитом. Контроллер работает с settings, sidebar и диалогами;
сам не рисует никакого UI.
"""

from __future__ import annotations

from pathlib import Path

from config.constants import DEFAULT_PROFILE_NAME_PREFIX
from core.models import Profile
from core.settings_store import save_settings
from ui.components.icon_picker import pick_icon
from ui.dialogs.profile_dialogs import (
    ask_delete_profile,
    ask_profile_name,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class ProfileActionController:
    """CRUD профилей + переименование + смена иконки."""

    def __init__(self, window):
        self._window = window

    # --- Поиск ---

    def find(self, pid: str) -> Profile | None:
        for p in self._window.settings.profiles:
            if p.id == pid:
                return p
        return None

    def next_number(self) -> int:
        prefix = DEFAULT_PROFILE_NAME_PREFIX + " "
        max_n = 0
        for p in self._window.settings.profiles:
            base = p.name_base
            if not base.startswith(prefix):
                continue
            try:
                n = int(base[len(prefix):])
            except ValueError as exc:
                logger.debug(
                    "Не разобран номер профиля %r: %r", base, exc,
                )
                continue
            if n > max_n:
                max_n = n
        return max_n + 1

    # --- Создание ---

    def add(self) -> Profile:
        n = self.next_number()
        profile = Profile(
            name_base=f"{DEFAULT_PROFILE_NAME_PREFIX} {n}",
            name_auto=True,
            icon_auto=True,
        )
        self._window.settings.profiles.append(profile)
        save_settings(self._window.settings)
        self._window.refresh_sidebar()
        self._window.refresh_main_view()
        self._window.open_profile(profile.id)
        self._window.set_status(f"Создан {profile.display_name}")
        return profile

    # --- Переименование ---

    def rename(self, pid: str) -> None:
        profile = self.find(pid)
        if profile is None:
            return

        new_name = ask_profile_name(
            self._window,
            profile.display_name,
            self._window.is_parent_visible(),
        )
        if new_name is None:
            return

        profile.name_manual = new_name
        profile.name_auto = False
        save_settings(self._window.settings)
        self._window.refresh_sidebar()
        self._reload_view_if_open(pid)
        self._window.refresh_main_view()
        self._window.set_status(
            f"Профиль переименован: {new_name}",
        )

    # --- Смена иконки ---

    def change_icon(self, pid: str) -> None:
        profile = self.find(pid)
        if profile is None:
            return

        exe_path = self.resolve_exe_path(profile)
        result = pick_icon(
            parent=self._window,
            current_icon=profile.icon,
            current_icon_auto=profile.icon_auto,
            exe_path=exe_path,
            parent_visible=self._window.is_parent_visible(),
        )
        if result is None:
            return

        profile.icon, profile.icon_auto = result
        save_settings(self._window.settings)
        self._window.refresh_sidebar()
        self._reload_view_if_open(pid)
        self._window.refresh_main_view()
        self._window.set_status("Иконка профиля обновлена")

    # --- Удаление ---

    def delete(self, pid: str) -> None:
        profile = self.find(pid)
        if profile is None:
            return

        if not ask_delete_profile(
            self._window,
            profile.display_name,
            self._window.is_parent_visible(),
        ):
            return

        removed_name = profile.display_name
        self._window.settings.profiles = [
            p for p in self._window.settings.profiles if p.id != pid
        ]
        save_settings(self._window.settings)
        self._window.refresh_sidebar()
        self._window.refresh_main_view()

        if self._window.active_profile_id == pid:
            self._window.show_main()

        self._window.set_status(f"Профиль удалён: {removed_name}")

    # --- Вспомогательное ---

    def resolve_exe_path(self, profile: Profile) -> Path | None:
        full = profile.exe_source_path()
        if not full:
            return None
        p = Path(full)
        if not p.is_file():
            return None
        return p

    def _reload_view_if_open(self, pid: str) -> None:
        if self._window.active_profile_id != pid:
            return
        view = self._window.router.get_view("profile")
        if view is None:
            return
        setter = getattr(view, "set_profile", None)
        if callable(setter):
            try:
                setter(pid)
            except Exception as exc:
                logger.error(
                    "Перезагрузка ProfileView упала: %r", exc,
                )
