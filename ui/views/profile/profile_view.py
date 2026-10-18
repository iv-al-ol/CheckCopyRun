"""Экран профиля: связывает шапку, форму и действия."""

from __future__ import annotations

import os

import customtkinter as ctk

from config.constants import (
    DEFAULT_PROFILE_ICON,
    PROFILE_BOTTOM_BAR_PADY_BOTTOM,
    PROFILE_BOTTOM_BAR_PADY_TOP,
    PROFILE_BOTTOM_BUTTON_HEIGHT,
    SEPARATOR_PADY,
)
from core.models import Profile
from core.settings_store import save_settings
from ui.components.button import VARIANT_SECONDARY, StyledButton
from ui.components.separator import make_separator
from ui.dialogs import ask_yes_no, show_error
from ui.views.base_view import BaseView
from ui.views.profile.profile_form import ProfileForm
from ui.views.profile.profile_header import ProfileHeader
from ui.views.profile.profile_path_controller import (
    ProfilePathController,
)
from ui.views.profile.profile_paths import (
    path_conflict_error,
    profile_subtitle,
)
from ui.views.profile.profile_process_controller import (
    ProfileProcessController,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_UTILITY_BUTTON_WIDTH = 160
_BUTTON_GAP = 8


class ProfileView(BaseView):
    """Форма профиля. Один экземпляр, переключается через set_profile."""

    def __init__(self, master, window):
        super().__init__(master, window)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._profile_id: str | None = None
        self._busy = False

        self._path_controller = ProfilePathController(
            window,
            get_profile=self._profile,
            on_changed=self._save_and_refresh,
            on_state_refresh=self._reload_from_profile,
        )
        self._process_controller = ProfileProcessController(
            window,
            get_profile=self._profile,
            on_busy_change=self._set_busy,
            on_reload=self._reload_from_profile,
        )

        self._header = ProfileHeader(self)
        self._header.grid(
            row=0, column=0, sticky="ew",
            padx=24, pady=(20, 12),
        )

        self._form = ProfileForm(
            self,
            on_pick_source=self._path_controller.pick_source,
            on_open_source=self._on_open_source_folder,
            on_pick_destination=self._path_controller.pick_destination,
            on_open_destination=self._on_open_destination_folder,
            on_pick_exe=self._path_controller.pick_exe,
            on_backup_toggle=self._on_backup_toggle,
            on_run_after_toggle=self._on_run_after_toggle,
            on_check_on_startup_toggle=self._on_check_on_startup_toggle,
            on_copy=self._process_controller.copy,
            on_run=self._process_controller.run,
        )
        self._form.grid(
            row=1, column=0, sticky="nsew",
            padx=24, pady=(0, 12),
        )

        self._build_separator()
        self._build_bottom_bar()

    # --- Публичное ---

    def set_profile(self, pid: str) -> None:
        self._profile_id = pid
        self._reload_from_profile()

    def on_show(self) -> None:
        self._reload_from_profile()

    # --- Раскладка ---

    def _build_separator(self) -> None:
        sep = make_separator(self)
        sep.grid(
            row=2, column=0, sticky="ew",
            padx=24, pady=SEPARATOR_PADY,
        )

    def _build_bottom_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(
            row=3, column=0, sticky="ew",
            padx=24,
            pady=(
                PROFILE_BOTTOM_BAR_PADY_TOP,
                PROFILE_BOTTOM_BAR_PADY_BOTTOM,
            ),
        )

        StyledButton(
            bar, text="Сменить иконку",
            variant=VARIANT_SECONDARY,
            width=_UTILITY_BUTTON_WIDTH,
            height=PROFILE_BOTTOM_BUTTON_HEIGHT,
            command=self._on_change_icon,
        ).pack(side="left", padx=(0, _BUTTON_GAP))

        StyledButton(
            bar, text="Переименовать",
            variant=VARIANT_SECONDARY,
            width=_UTILITY_BUTTON_WIDTH,
            height=PROFILE_BOTTOM_BUTTON_HEIGHT,
            command=self._on_rename,
        ).pack(side="left", padx=(0, _BUTTON_GAP))

        StyledButton(
            bar, text="Сбросить настройки",
            variant=VARIANT_SECONDARY,
            width=_UTILITY_BUTTON_WIDTH,
            height=PROFILE_BOTTOM_BUTTON_HEIGHT,
            command=self._on_reset,
        ).pack(side="left", padx=(0, _BUTTON_GAP))

        StyledButton(
            bar, text="Удалить",
            variant=VARIANT_SECONDARY,
            width=_UTILITY_BUTTON_WIDTH,
            height=PROFILE_BOTTOM_BUTTON_HEIGHT,
            command=self._on_delete,
        ).pack(side="left")

    # --- Загрузка состояния ---

    def _profile(self) -> Profile | None:
        if self._profile_id is None:
            return None
        for p in self.window.settings.profiles:
            if p.id == self._profile_id:
                return p
        return None

    def _reload_from_profile(self) -> None:
        profile = self._profile()
        if profile is None:
            self._header.clear()
            self._form.update_values(
                source="",
                destination="",
                exe_name="",
                create_backup=True,
                run_after_copy=False,
                check_on_startup=False,
            )
            self._form.update_open_buttons(
                source_enabled=False,
                destination_enabled=False,
            )
            return

        self._header.update(profile, profile_subtitle(profile))
        self._form.update_values(
            source=profile.source,
            destination=profile.destination,
            exe_name=_exe_name(profile),
            create_backup=profile.create_backup,
            run_after_copy=profile.run_after_copy,
            check_on_startup=profile.check_on_startup,
        )
        self._update_open_buttons(profile)
        self._update_buttons_state(profile)

    def _update_open_buttons(self, profile: Profile) -> None:
        self._form.update_open_buttons(
            source_enabled=bool(profile.source),
            destination_enabled=bool(profile.destination),
        )

    def _update_buttons_state(self, profile: Profile) -> None:
        if self._busy:
            self._form.update_buttons_state(
                copy_enabled=False, run_enabled=False,
            )
            return

        conflict = path_conflict_error(
            profile.source, profile.destination,
        )
        if conflict:
            self._form.update_buttons_state(
                copy_enabled=False, run_enabled=False,
            )
            return

        self._form.update_buttons_state(
            copy_enabled=profile.can_copy(),
            run_enabled=profile.can_run(),
        )

    # --- Открытие папок ---

    def _on_open_source_folder(self) -> None:
        if self._path_controller.open_source():
            return

        profile = self._profile()
        if profile is None:
            return

        show_error(
            self.window,
            "Не удалось открыть папку",
            (
                "Не удалось открыть или создать папку-источник:\n"
                f"{profile.source or '—'}\n\n"
                "Проверьте, что путь доступен и у приложения "
                "есть права."
            ),
        )

    def _on_open_destination_folder(self) -> None:
        if self._path_controller.open_destination():
            return

        profile = self._profile()
        if profile is None:
            return

        show_error(
            self.window,
            "Не удалось открыть папку",
            (
                "Не удалось открыть или создать целевую папку:\n"
                f"{profile.destination or '—'}\n\n"
                "Проверьте, что путь доступен и у приложения "
                "есть права."
            ),
        )

    # --- Чекбоксы ---

    def _on_backup_toggle(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        profile.create_backup = self._form.create_backup
        save_settings(self.window.settings)

    def _on_run_after_toggle(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        profile.run_after_copy = self._form.run_after_copy
        save_settings(self.window.settings)

    def _on_check_on_startup_toggle(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        profile.check_on_startup = self._form.check_on_startup
        save_settings(self.window.settings)
        state = "включена" if profile.check_on_startup else "выключена"
        self.window.set_status(
            f"Автопроверка при запуске {state}",
        )

    # --- Действия над профилем ---

    def _on_change_icon(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        self.window.profile_actions.change_icon(profile.id)

    def _on_rename(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        self.window.profile_actions.rename(profile.id)

    def _on_delete(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        self.window.profile_actions.delete(profile.id)

    # --- Сброс профиля ---

    def _on_reset(self) -> None:
        profile = self._profile()
        if profile is None:
            return

        confirm = ask_yes_no(
            self.window,
            "Сброс настроек профиля",
            (
                f"Сбросить настройки профиля "
                f"«{profile.display_name}»?\n\n"
                f"Будут очищены исходная и целевая директории, "
                f"выбранное приложение и его иконка.\n"
                f"Имя профиля и чекбоксы сохранятся."
            ),
            yes_text="Сбросить",
            no_text="Отмена",
            parent_visible=True,
        )
        if not confirm:
            return

        profile.source = ""
        profile.destination = ""
        profile.exe_relative = ""
        profile.icon = DEFAULT_PROFILE_ICON
        profile.icon_auto = True

        self._save_and_refresh()
        self.window.set_status("Настройки профиля сброшены")

    # --- Вспомогательное ---

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        profile = self._profile()
        if profile is not None:
            self._update_buttons_state(profile)

    def _save_and_refresh(self) -> None:
        save_settings(self.window.settings)
        self.window.refresh_sidebar()
        self._reload_from_profile()


def _exe_name(profile: Profile) -> str:
    if not profile.exe_relative:
        return ""
    return os.path.basename(profile.exe_relative)
