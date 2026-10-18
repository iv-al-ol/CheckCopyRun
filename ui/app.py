"""Главное окно приложения."""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from config.constants import (
    APP_TITLE,
    THEME_DEFAULT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from core.models import AppSettings, Profile
from core.paths import get_asset_path
from core.settings_store import load_settings, save_settings
from services.copy_service import (
    CopyResult,
    CopyService,
    format_cancel_status,
)
from services.startup_check import StartupCheckQueue
from ui.components.context_menu import ContextMenu
from ui.components.status_bar import StatusBar
from ui.dialogs import ask_yes_no, show_error
from ui.layouts.main_layout import MainLayout
from ui.layouts.sidebar import (
    KEY_MAIN,
    KEY_SETTINGS,
    parse_profile_key,
    profile_key,
)
from ui.navigation.router import Router
from ui.profile_actions import ProfileActionController
from ui.themes import apply_theme
from ui.views.main_view import MainView
from ui.views.profile import ProfileView
from ui.views.profile.profile_paths import (
    ensure_directory,
    source_error,
)
from ui.views.settings_view import SettingsView
from ui.window_geometry import (
    WindowGeometryTracker,
    apply_default_geometry,
    capture_geometry,
    is_valid_geometry_string,
    try_restore_geometry,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_STARTUP_CHECK_DELAY_MS = 700


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.settings: AppSettings = load_settings()
        apply_theme(self.settings.theme or THEME_DEFAULT)

        self.title(APP_TITLE)
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self.active_profile_id: str | None = None
        self._icon_photo = None
        self._closing = False

        self.copy_service = CopyService(
            scheduler=lambda fn: self.after(0, fn),
        )
        self.profile_actions = ProfileActionController(self)
        self._geometry_tracker = WindowGeometryTracker(self)

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

        self.startup_checker = StartupCheckQueue(
            window=self,
            copy_service=self.copy_service,
            set_status_progress=self.set_status_progress,
            on_finish=self.refresh_main_view,
        )

        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self._geometry_tracker.start()
        self.after(_STARTUP_CHECK_DELAY_MS, self._run_startup_check)

    # --- Иконка окна ---

    def _apply_window_icon(self) -> None:
        icon_path = get_asset_path("icon.ico")
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
        if saved and is_valid_geometry_string(saved):
            if try_restore_geometry(self, saved):
                return
            logger.debug(
                "Сохранённая геометрия %r не применена — дефолт",
                saved,
            )
        apply_default_geometry(self)

    def _save_geometry(self) -> None:
        geometry = capture_geometry(self)
        if geometry is not None:
            self.settings.window_geometry = geometry

    def get_last_visible_rect(
        self,
    ) -> tuple[int, int, int, int] | None:
        return self._geometry_tracker.get_last_visible_rect()

    # --- Роутер ---

    def _build_router(self) -> None:
        content = self.layout.content
        self.router = Router(content)

        self.router.register(
            "main",
            lambda: MainView(content, self),
        )
        self.router.register(
            "settings",
            lambda: SettingsView(content, self),
        )
        self.router.register(
            "profile",
            lambda: ProfileView(content, self),
        )

    def _restore_last_view(self) -> None:
        key = self.settings.last_view or KEY_MAIN
        pid = parse_profile_key(key)

        if pid is not None and self.profile_actions.find(pid) is None:
            key = KEY_MAIN
        elif pid is None and key not in (KEY_MAIN, KEY_SETTINGS):
            key = KEY_MAIN

        self._on_sidebar_select(key)

    # --- Навигация ---

    def _on_sidebar_select(self, key: str) -> None:
        try:
            if key == KEY_MAIN:
                self.active_profile_id = None
                self.router.show("main")
            elif key == KEY_SETTINGS:
                self.active_profile_id = None
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
        self.active_profile_id = pid

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

    def open_profile(self, pid: str) -> None:
        self._on_sidebar_select(profile_key(pid))

    def show_main(self) -> None:
        self._on_sidebar_select(KEY_MAIN)

    def is_parent_visible(self) -> bool:
        try:
            return self.state() in ("normal", "zoomed")
        except Exception as exc:
            logger.debug("state(): %r", exc)
            return True

    # --- Публичное API ---

    def save_settings_now(self) -> None:
        try:
            save_settings(self.settings)
        except Exception as exc:
            logger.error("Не удалось сохранить настройки: %r", exc)

    def refresh_sidebar(self) -> None:
        self.layout.sidebar.rebuild_profiles(self.settings.profiles)

    def refresh_main_view(self) -> None:
        view = self.router.get_view("main")
        if view is None:
            return
        on_show = getattr(view, "on_show", None)
        if callable(on_show):
            try:
                on_show()
            except Exception as exc:
                logger.debug("on_show MainView: %r", exc)

    def reset_all_settings(self) -> None:
        try:
            if self.copy_service.is_running:
                self.copy_service.cancel()

            self.startup_checker.cancel()

            self.settings = AppSettings()
            apply_theme(self.settings.theme or THEME_DEFAULT)
            save_settings(self.settings)

            self.active_profile_id = None
            self.layout.sidebar.set_active(KEY_MAIN)
            self.refresh_sidebar()
            self.router.show("main")
            self.refresh_main_view()

            view = self.router.get_view("settings")
            if view is not None:
                on_show = getattr(view, "on_show", None)
                if callable(on_show):
                    try:
                        on_show()
                    except Exception as exc:
                        logger.debug(
                            "on_show SettingsView: %r", exc,
                        )

            self.set_status(
                "Настройки сброшены к значениям по умолчанию",
            )
            logger.info("Все настройки сброшены пользователем")
        except Exception as exc:
            logger.error("Ошибка сброса настроек: %r", exc)
            self.set_status(f"Ошибка сброса: {exc}")

    # --- Автопроверка при старте ---

    def _run_startup_check(self) -> None:
        if self._closing:
            return
        self.startup_checker.start(self.settings.profiles)

    # --- Проверка + запуск (кнопка ▶) ---

    def run_with_check(self, pid: str) -> None:
        """Копирует директорию и запускает приложение.

        Используется кнопкой ▶ в сайдбаре и на плитке главной.
        Соответствует тултипу «Проверить директорию и запустить
        приложение»: сначала копирование, потом запуск. При
        ошибках копирования запуск не выполняется.
        """
        profile = self.profile_actions.find(pid)
        if profile is None:
            return

        if self.copy_service.is_running:
            self.set_status("Копирование уже выполняется")
            return

        src_err = source_error(profile.source)
        if src_err is not None:
            show_error(
                self,
                "Нельзя запустить",
                src_err,
                parent_visible=self.is_parent_visible(),
            )
            return

        if not profile.destination:
            show_error(
                self,
                "Нельзя запустить",
                "Целевая директория не задана.",
                parent_visible=self.is_parent_visible(),
            )
            return

        if not ensure_directory(profile.destination):
            show_error(
                self,
                "Нельзя запустить",
                (
                    "Не удалось создать целевую директорию:\n"
                    f"{profile.destination}\n\n"
                    "Проверьте, что диск доступен и есть права "
                    "на запись."
                ),
                parent_visible=self.is_parent_visible(),
            )
            return

        self.set_status_progress("Копирование…", 0.0)

        started = self.copy_service.start(
            source=profile.source,
            destination=profile.destination,
            create_backup=profile.create_backup,
            on_progress=self._on_run_check_progress,
            on_done=lambda r, p=profile: self._on_run_check_done(r, p),
            on_error=self._on_run_check_error,
            hash_cache_enabled=self.settings.hash_cache_enabled,
        )
        if not started:
            self.set_status("Не удалось запустить копирование")

    def _on_run_check_progress(self, progress) -> None:
        self.set_status_progress(
            f"Копирование: {progress.processed}/{progress.total}",
            progress.percent / 100.0,
        )

    def _on_run_check_done(
        self, result: CopyResult, profile: Profile,
    ) -> None:
        if result.cancelled:
            self.set_status_progress(
                format_cancel_status(result), None,
            )
            return

        if result.errors > 0:
            self.set_status_progress(
                f"Копирование с {result.errors} ошибками — "
                f"запуск отменён",
                None,
            )
            show_error(
                self,
                "Нельзя запустить приложение",
                (
                    f"Копирование завершилось с "
                    f"{result.errors} ошибк(ами).\n\n"
                    "Подробности — в логе."
                ),
                parent_visible=self.is_parent_visible(),
            )
            return

        parts = [
            f"скопировано {result.copied}",
            f"пропущено {result.skipped}",
        ]
        self.set_status_progress(
            "Копирование завершено: " + ", ".join(parts),
            None,
        )

        profile.touch()
        save_settings(self.settings)

        full = profile.exe_full_path()
        if not full or not Path(full).is_file():
            show_error(
                self,
                "Нельзя запустить приложение",
                (
                    "Файл приложения не найден:\n"
                    f"{full or '—'}\n\n"
                    "Убедитесь, что приложение было в исходной "
                    "директории и успешно скопировано."
                ),
                parent_visible=self.is_parent_visible(),
            )
            return

        from services.launcher import LaunchError, launch_exe
        try:
            launch_exe(full)
        except LaunchError as exc:
            show_error(
                self,
                "Ошибка запуска",
                str(exc),
                parent_visible=self.is_parent_visible(),
            )
            return

        self.set_status(f"Запущено: {Path(full).name}")

    def _on_run_check_error(self, message: str) -> None:
        self.set_status_progress(f"Ошибка: {message}", None)
        show_error(
            self,
            "Ошибка копирования",
            message,
            parent_visible=self.is_parent_visible(),
        )

    # --- Действия с профилями: тонкие обёртки над контроллером ---

    def _on_add_profile(self) -> None:
        self.profile_actions.add()

    def _on_profile_context(self, pid: str, x: int, y: int) -> None:
        profile = self.profile_actions.find(pid)
        if profile is None:
            return

        menu = ContextMenu(self)
        menu.add_item(
            "Переименовать",
            lambda: self.profile_actions.rename(pid),
            icon="✏️",
        )
        menu.add_item(
            "Сменить иконку",
            lambda: self.profile_actions.change_icon(pid),
            icon="🎨",
        )
        menu.add_separator()
        menu.add_item(
            "Удалить",
            lambda: self.profile_actions.delete(pid),
            icon="🗑",
            danger=True,
        )
        menu.show(x, y)

    def _on_run_profile(self, pid: str) -> None:
        """Кнопка ▶ в сайдбаре: проверка + запуск."""
        self.run_with_check(pid)

    # --- Статус-бар ---

    def set_status(self, text: str) -> None:
        self.after(0, lambda: self.status_bar.set_text(text))

    def set_progress(self, value: float | None) -> None:
        self.after(0, lambda: self.status_bar.show_progress(value))

    def set_status_progress(
        self, text: str, value: float | None,
    ) -> None:
        def apply() -> None:
            self.status_bar.set_text(text)
            self.status_bar.show_progress(value)
        self.after(0, apply)

    # --- Закрытие ---

    def _on_close_request(self) -> None:
        if self._closing:
            return

        if self.settings.confirm_on_exit:
            confirmed = ask_yes_no(
                self,
                "Закрытие приложения",
                "Закрыть CheckCopyRun?",
                yes_text="Закрыть",
                no_text="Отмена",
                parent_visible=self.is_parent_visible(),
            )
            if not confirmed:
                return

        self._closing = True
        self.startup_checker.cancel()
        try:
            if self.copy_service.is_running:
                self.copy_service.cancel()
            self._save_geometry()
            self.settings.last_view = (
                self.router.current or KEY_MAIN
            )
            save_settings(self.settings)
        except Exception as exc:
            logger.error("Ошибка сохранения при закрытии: %r", exc)
        self.destroy()
