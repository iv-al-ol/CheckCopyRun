"""Главное окно приложения."""

from __future__ import annotations

import re
from pathlib import Path

import customtkinter as ctk

from config.constants import (
    APP_TITLE,
    DEFAULT_PROFILE_NAME_PREFIX,
    THEME_DEFAULT,
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_DEFAULT_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from core.models import AppSettings, Profile
from core.settings_store import load_settings, save_settings
from services.copy_service import CopyService
from ui.components.context_menu import ContextMenu
from ui.components.icon_picker import pick_icon
from ui.components.status_bar import StatusBar
from ui.dialogs.profile_dialogs import (
    ask_delete_profile,
    ask_profile_name,
)
from ui.layouts.main_layout import MainLayout
from ui.layouts.sidebar import (
    KEY_MAIN,
    KEY_SETTINGS,
    parse_profile_key,
    profile_key,
)
from ui.navigation.router import Router
from ui.themes import apply_theme
from ui.views.profile_view import ProfileView
from ui.views.stub_view import StubView
from utils.logger import get_logger

logger = get_logger(__name__)

_GEOMETRY_RE = re.compile(r"^\d+x\d+\+-?\d+\+-?\d+$")


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.settings: AppSettings = load_settings()
        apply_theme(self.settings.theme or THEME_DEFAULT)

        self.title(APP_TITLE)
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self._active_profile_id: str | None = None
        self._icon_photo = None

        # --- Сервисы ---
        self.copy_service = CopyService(
            scheduler=lambda fn: self.after(0, fn),
        )

        self._apply_window_icon()
        self._restore_or_default_geometry()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.layout = MainLayout(
            self,
            on_select=self._on_sidebar_select,
            on_add_profile=self._on_add_profile,
            on_run_profile=self._on_run_profile,
            on_profile_context=self._on_profile_context,
        )
        self.layout.grid(row=0, column=0, sticky="nsew")

        self.status_bar = StatusBar(self)
        self.status_bar.grid(row=1, column=0, sticky="ew")

        self._build_router()

        self.refresh_sidebar()
        self._restore_last_view()

        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

    # --- Иконка окна ---

    def _apply_window_icon(self) -> None:
        icon_path = (
            Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
        )
        if not icon_path.exists():
            logger.warning("Иконка не найдена: %s", icon_path)
            return

        try:
            self.iconbitmap(str(icon_path))
        except Exception as exc:
            logger.warning("iconbitmap не удался: %r", exc)

        try:
            from PIL import Image, ImageTk
        except ImportError as exc:
            logger.debug("Pillow недоступен: %r", exc)
            return

        try:
            img = Image.open(icon_path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            photo = ImageTk.PhotoImage(img)
            self.iconphoto(True, photo)
            self._icon_photo = photo
        except Exception as exc:
            logger.warning("iconphoto не удался: %r", exc)

    # --- Геометрия ---

    def _restore_or_default_geometry(self) -> None:
        saved = self.settings.window_geometry
        if saved and _GEOMETRY_RE.match(saved):
            try:
                self.geometry(saved)
                return
            except Exception as exc:
                logger.debug(
                    "Не удалось применить геометрию %s: %r", saved, exc,
                )

        w, h = WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    # --- Роутер ---

    def _build_router(self) -> None:
        content = self.layout.content
        self.router = Router(content)

        self.router.register(
            "main",
            lambda: StubView(content, self, title="Главный"),
        )
        self.router.register(
            "settings",
            lambda: StubView(content, self, title="Настройки"),
        )
        self.router.register(
            "profile",
            lambda: ProfileView(content, self),
        )

    def _restore_last_view(self) -> None:
        key = self.settings.last_view or KEY_MAIN
        pid = parse_profile_key(key)

        if pid is not None and self._find_profile(pid) is None:
            key = KEY_MAIN
        elif pid is None and key not in (KEY_MAIN, KEY_SETTINGS):
            key = KEY_MAIN

        self._on_sidebar_select(key)

    # --- Навигация ---

    def _on_sidebar_select(self, key: str) -> None:
        try:
            if key == KEY_MAIN:
                self._active_profile_id = None
                self.router.show("main")
            elif key == KEY_SETTINGS:
                self._active_profile_id = None
                self.router.show("settings")
            else:
                pid = parse_profile_key(key)
                if pid is None:
                    logger.warning(
                        "Неизвестный ключ навигации: %r", key,
                    )
                    return
                self._show_profile(pid)
            self.layout.sidebar.set_active(key)
        except Exception as exc:
            logger.error("Ошибка навигации %r: %r", key, exc)

    def _show_profile(self, pid: str) -> None:
        self._active_profile_id = pid

        view = self.router.get_or_create("profile")
        if view is None:
            logger.warning("ProfileView не создан")
            self.set_status("Не удалось открыть профиль")
            return

        setter = getattr(view, "set_profile", None)
        if callable(setter):
            try:
                setter(pid)
            except Exception as exc:
                logger.error("set_profile(%r) упал: %r", pid, exc)

        self.router.show("profile")

    def show_main(self) -> None:
        self._on_sidebar_select(KEY_MAIN)

    # --- Профили: поиск и нумерация ---

    def _find_profile(self, pid: str) -> Profile | None:
        for p in self.settings.profiles:
            if p.id == pid:
                return p
        return None

    def _next_profile_number(self) -> int:
        prefix = DEFAULT_PROFILE_NAME_PREFIX + " "
        max_n = 0
        for p in self.settings.profiles:
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

    def refresh_sidebar(self) -> None:
        self.layout.sidebar.rebuild_profiles(self.settings.profiles)

    # --- Профили: действия ---

    def _on_add_profile(self) -> None:
        n = self._next_profile_number()
        profile = Profile(
            name_base=f"{DEFAULT_PROFILE_NAME_PREFIX} {n}",
            name_auto=True,
            icon_auto=True,
        )
        self.settings.profiles.append(profile)
        save_settings(self.settings)
        self.refresh_sidebar()
        self._on_sidebar_select(profile_key(profile.id))
        self.set_status(f"Создан {profile.display_name}")

    def _on_run_profile(self, pid: str) -> None:
        profile = self._find_profile(pid)
        if profile is None:
            self.set_status(f"Профиль {pid[:8]} не найден")
            return

        from services.launcher import LaunchError, launch_exe
        try:
            launch_exe(profile.exe_full_path())
            self.set_status(f"Запущено: {profile.display_name}")
        except LaunchError as exc:
            self.set_status(f"Ошибка запуска: {exc}")

    def _on_profile_context(self, pid: str, x: int, y: int) -> None:
        profile = self._find_profile(pid)
        if profile is None:
            return

        menu = ContextMenu(self)
        menu.add_item(
            "Переименовать",
            lambda: self._rename_profile(pid),
            icon="✏️",
        )
        menu.add_item(
            "Сменить иконку",
            lambda: self._change_icon(pid),
            icon="🎨",
        )
        menu.add_separator()
        menu.add_item(
            "Удалить",
            lambda: self._delete_profile(pid),
            icon="🗑",
            danger=True,
        )
        menu.show(x, y)

    def _rename_profile(self, pid: str) -> None:
        profile = self._find_profile(pid)
        if profile is None:
            return

        new_name = ask_profile_name(
            self, profile.display_name, self._parent_visible(),
        )
        if new_name is None:
            return

        profile.name_manual = new_name
        profile.name_auto = False
        save_settings(self.settings)
        self.refresh_sidebar()
        self._reload_profile_view_if_open(pid)
        self.set_status(f"Профиль переименован: {new_name}")

    def _change_icon(self, pid: str) -> None:
        profile = self._find_profile(pid)
        if profile is None:
            return

        exe_path = self._resolve_exe_path(profile)
        result = pick_icon(
            parent=self,
            current_icon=profile.icon,
            current_icon_auto=profile.icon_auto,
            exe_path=exe_path,
            parent_visible=self._parent_visible(),
        )
        if result is None:
            return

        profile.icon, profile.icon_auto = result
        save_settings(self.settings)
        self.refresh_sidebar()
        self._reload_profile_view_if_open(pid)
        self.set_status("Иконка профиля обновлена")

    def _delete_profile(self, pid: str) -> None:
        profile = self._find_profile(pid)
        if profile is None:
            return

        if not ask_delete_profile(
            self, profile.display_name, self._parent_visible(),
        ):
            return

        removed_name = profile.display_name
        self.settings.profiles = [
            p for p in self.settings.profiles if p.id != pid
        ]
        save_settings(self.settings)
        self.refresh_sidebar()

        if self._active_profile_id == pid:
            self._active_profile_id = None
            self.show_main()

        self.set_status(f"Профиль удалён: {removed_name}")

    # --- Вспомогательное ---

    def _reload_profile_view_if_open(self, pid: str) -> None:
        if self._active_profile_id != pid:
            return
        view = self.router.get_view("profile")
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

    def _resolve_exe_path(self, profile: Profile) -> Path | None:
        full = profile.exe_full_path()
        if not full:
            return None
        p = Path(full)
        if not p.is_file():
            return None
        return p

    def _parent_visible(self) -> bool:
        try:
            return self.state() in ("normal", "zoomed")
        except Exception as exc:
            logger.debug("state(): %r", exc)
            return True

    # --- Статус-бар ---

    def set_status(self, text: str) -> None:
        self.after(0, lambda: self.status_bar.set_text(text))

    def set_progress(self, value: float | None) -> None:
        self.after(0, lambda: self.status_bar.show_progress(value))

    def set_status_progress(self, text: str, value: float | None) -> None:
        def apply() -> None:
            self.status_bar.set_text(text)
            self.status_bar.show_progress(value)
        self.after(0, apply)

    # --- Закрытие ---

    def _on_close_request(self) -> None:
        try:
            if self.copy_service.is_running:
                self.copy_service.cancel()
            self._save_geometry()
            self.settings.last_view = self.router.current or KEY_MAIN
            save_settings(self.settings)
        except Exception as exc:
            logger.error("Ошибка сохранения при закрытии: %r", exc)
        self.destroy()

    def _save_geometry(self) -> None:
        try:
            w = self.winfo_width()
            h = self.winfo_height()
            x = self.winfo_x()
            y = self.winfo_y()
        except Exception as exc:
            logger.debug("Не удалось прочитать геометрию окна: %r", exc)
            return
        if w <= 1 or h <= 1:
            return
        self.settings.window_geometry = f"{w}x{h}+{x}+{y}"
