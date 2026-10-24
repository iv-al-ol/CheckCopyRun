"""Главное окно приложения."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import customtkinter as ctk

from config.constants import (
    APP_NAME,
    APP_TITLE,
    THEME_DEFAULT,
)
from core.models import AppSettings, Profile
from core.paths import ensure_directory, get_asset_path
from core.settings_store import load_settings, save_settings
from services.cas.backup_cleanup import (
    CleanupPolicy,
    cleanup_states,
)
from services.copy.copy_service import (
    PHASE_SAVE_SCAN,
    PHASE_SAVE_STORE,
    CopyProgress,
    CopyResult,
    CopyService,
    format_cancel_status,
    format_copy_status,
    format_mirror_suffix,
)
from services.copy.mirror_check import scan_mirror_diff
from services.monitor.monitor_service import MonitorService
from services.restore.disk_space import check_disk_space
from services.restore.restore_service import (
    RestoreProgress,
    RestoreResult,
    RestoreService,
    format_restore_status,
)
from services.startup_check import StartupCheckQueue
from services.system.icon_cleanup import cleanup_unused_icons
from services.system.notifier import (
    ChainNotifier,
    build_fallback_notifier,
)
from services.system.tray_manager import TrayManager
from ui.components.context_menu import ContextMenu
from ui.components.status_bar import StatusBar
from ui.components.toast import ToastManager, ToastNotifier
from ui.dialogs import ask_yes_no, show_error
from ui.dialogs._icon import apply_app_icon
from ui.dialogs.disk_space import confirm_insufficient_space
from ui.dialogs.mirror_confirm import confirm_mirror
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
from ui.views.profile.profile_paths import source_error
from ui.views.settings import SettingsView
from ui.window_geometry import (
    WindowGeometryTracker,
    apply_default_geometry,
    capture_geometry,
    effective_min_size,
    is_valid_geometry_string,
    try_restore_geometry,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_STARTUP_CHECK_DELAY_MS = 700

# Мониторинг стартует после автопроверки, чтобы первый цикл
# не соревновался с копированием за диск.
_MONITOR_START_DELAY_MS = 2500

# Термин для restore_point в UI.
_RETURN_POINT_LABEL = "Точка возврата"


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.settings: AppSettings = load_settings()

        try:
            cleanup_unused_icons(self.settings)
        except Exception as exc:
            logger.debug("startup cleanup_unused_icons: %r", exc)

        apply_theme(self.settings.theme or THEME_DEFAULT)

        self.title(APP_TITLE)
        min_w, min_h = effective_min_size(self)
        self.minsize(min_w, min_h)

        self.active_profile_id: str | None = None
        self._icon_photo = None
        self._closing = False

        self.copy_service = CopyService(
            scheduler=lambda fn: self.after(0, fn),
        )
        self.restore_service = RestoreService(
            scheduler=lambda fn: self.after(0, fn),
        )
        self.profile_actions = ProfileActionController(self)
        self._geometry_tracker = WindowGeometryTracker(self)

        self._tray = TrayManager(
            icon_path=get_asset_path("icon.ico"),
            title=APP_NAME,
            on_show=self._on_tray_show,
            on_quit=self._on_tray_quit,
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
        self.status_bar.set_on_cancel(self.cancel_current)

        self._build_router()

        self.refresh_sidebar()
        # Всегда открываем «Главный» раздел при запуске.
        self._on_sidebar_select(KEY_MAIN)

        self.startup_checker = StartupCheckQueue(
            window=self,
            copy_service=self.copy_service,
            set_status_progress=self.set_status_progress,
            on_finish=self.refresh_main_view,
        )

        self.toast_manager = ToastManager(self)
        self.monitor = MonitorService(
            notifier=ChainNotifier([
                ToastNotifier(self.toast_manager, self),
                build_fallback_notifier(self._tray),
            ]),
            is_busy=self._is_profile_busy,
            scheduler=lambda fn: self.after(0, fn),
        )
        self.monitor.configure(
            self.settings.profiles, self.settings,
        )

        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self._geometry_tracker.start()

        if self.settings.start_minimized:
            self._hide_to_tray()

        self.after(_STARTUP_CHECK_DELAY_MS, self._run_startup_check)
        self.after(_MONITOR_START_DELAY_MS, self.refresh_monitor_config)

    # --- Системный трей ---

    def _on_tray_show(self) -> None:
        """Восстановление окна из трея (вызывается из pystray)."""
        self.after(0, self._show_window)

    def _show_window(self) -> None:
        """Показать окно. Трей продолжает работать."""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception as exc:
            logger.error("Ошибка восстановления окна: %r", exc)

    def _on_tray_quit(self) -> None:
        """Принудительный выход (вызывается из pystray)."""
        self.after(0, lambda: self._on_close_request(force=True))

    def _hide_to_tray(self) -> None:
        if not self._tray.start():
            logger.warning("Не удалось запустить трей — закрываю окно")
            self._on_close_request(force=True)
            return

        try:
            self.withdraw()
            logger.info("Окно свёрнуто в трей")
        except Exception as exc:
            logger.error("Ошибка withdraw: %r", exc)

    # --- Публичный API: копирование с UI-обвязкой ---

    def ensure_disk_space(
        self,
        source: str,
        destination: str,
        create_backup: bool,
    ) -> bool:
        check = check_disk_space(source, destination, create_backup)
        if check is None:
            return True
        if check.ok:
            return True

        return confirm_insufficient_space(
            self, check, self.is_parent_visible(),
        )

    def start_copy_with_ui(
        self,
        *,
        source: str,
        destination: str,
        create_backup: bool,
        hash_cache_enabled: bool,
        mirror_mode: bool,
        profile_name: str = "",
        is_startup_check: bool = False,
        on_progress: Callable[[CopyProgress], None],
        on_done: Callable[[CopyResult], None],
        on_error: Callable[[str], None],
    ) -> bool:
        """Запускает копирование с UI-обвязкой."""
        if self.restore_service.is_running:
            self.set_status("Восстановление уже выполняется")
            return False

        if mirror_mode:
            try:
                stats = scan_mirror_diff(source, destination)
            except Exception as exc:
                logger.warning("pre-scan mirror упал: %r", exc)
                stats = None

            if (
                stats is not None
                and stats.requires_confirmation
                and not confirm_mirror(
                    self,
                    stats,
                    self.is_parent_visible(),
                    profile_name=profile_name,
                    is_startup_check=is_startup_check,
                )
            ):
                return False

        def wrapped_done(result: CopyResult) -> None:
            self.status_bar.show_cancel_button(False)

            if not result.cancelled and result.errors == 0:
                self._cleanup_states_for(destination)

            on_done(result)
            self.refresh_current_profile_view()

        def wrapped_error(message: str) -> None:
            self.status_bar.show_cancel_button(False)
            on_error(message)

        started = self.copy_service.start(
            source=source,
            destination=destination,
            create_backup=create_backup,
            on_progress=on_progress,
            on_done=wrapped_done,
            on_error=wrapped_error,
            hash_cache_enabled=hash_cache_enabled,
            mirror_mode=mirror_mode,
        )
        if started:
            self.status_bar.show_cancel_button(True)
        return started

    def cancel_copy(self) -> None:
        if not self.copy_service.is_running:
            return
        self.status_bar.show_cancel_button(False)
        self.set_status_progress("Отмена…", None)
        self.copy_service.cancel()

    # --- Публичный API: восстановление с UI-обвязкой ---

    def start_restore_with_ui(
        self,
        *,
        backup_state_ref: str,
        destination: str,
        profile_name: str = "",
        on_done: Callable[[RestoreResult], None],
        on_error: Callable[[str], None] | None = None,
    ) -> bool:
        """Запускает восстановление к указанному state.

        Перед изменениями destination автоматически создаётся
        restore_point (точка возврата) — при неудаче restore
        можно откатить.
        """
        if self.copy_service.is_running:
            self.set_status("Копирование уже выполняется")
            return False

        def wrapped_done(result: RestoreResult) -> None:
            self.status_bar.show_cancel_button(False)
            self._show_restore_status(result, profile_name)
            on_done(result)
            self.refresh_current_profile_view()

        def wrapped_error(message: str) -> None:
            self.status_bar.show_cancel_button(False)
            if on_error is not None:
                on_error(message)
                return
            self.set_status_progress(
                f"Ошибка восстановления: {message}", None,
            )
            show_error(
                self,
                "Ошибка восстановления",
                message,
                parent_visible=self.is_parent_visible(),
            )

        started = self.restore_service.start(
            backup_state_ref=backup_state_ref,
            destination=destination,
            on_progress=self._on_restore_progress,
            on_done=wrapped_done,
            on_error=wrapped_error,
        )
        if started:
            self.set_status_progress("Восстановление…", 0.0)
            self.status_bar.show_cancel_button(True)
        return started

    def _on_restore_progress(
        self, progress: RestoreProgress,
    ) -> None:
        self.set_status_progress(
            f"Восстановление: "
            f"{progress.processed}/{progress.total}",
            progress.percent / 100.0,
        )

    def _show_restore_status(
        self,
        result: RestoreResult,
        profile_name: str = "",
    ) -> None:
        text = format_restore_status(result)
        if profile_name:
            text = f"{profile_name}: {text}"
        if result.restore_point_path:
            point_name = Path(
                result.restore_point_path,
            ).name
            text += f"  ·  {_RETURN_POINT_LABEL}: {point_name}"
        self.set_status_progress(text, None)

    def cancel_current(self) -> None:
        """Отменяет текущую длительную операцию."""
        if self.copy_service.is_running:
            self.cancel_copy()
            return
        if self.restore_service.is_running:
            self.cancel_restore()

    def cancel_restore(self) -> None:
        if not self.restore_service.is_running:
            return
        self.status_bar.show_cancel_button(False)
        self.set_status_progress("Отмена…", None)
        self.restore_service.cancel()

    def _cleanup_states_for(self, destination: str) -> None:
        s = self.settings
        policy = CleanupPolicy(
            keep_last_enabled=s.backup_keep_last_enabled,
            keep_last_n=s.backup_keep_last_n,
            delete_older_enabled=s.backup_delete_older_enabled,
            delete_older_days=s.backup_delete_older_days,
        )
        if not policy.is_active:
            return
        try:
            result = cleanup_states(destination, policy)
            if result.deleted_count:
                logger.info(
                    "Очистка состояний для %s: удалено %d, "
                    "blob-ов удалено %d, ошибок %d",
                    destination,
                    result.deleted_count,
                    result.blobs_deleted,
                    len(result.errors),
                )
        except Exception as exc:
            logger.warning(
                "cleanup_states для %s упал: %r",
                destination, exc,
            )

    # --- Иконка окна ---

    def _apply_window_icon(self) -> None:
        try:
            apply_app_icon(self, taskbar=True)
        except Exception as exc:
            logger.warning("Иконка окна не установлена: %r", exc)

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

    # --- Навигация ---

    def _on_sidebar_select(self, key: str) -> None:
        try:
            if key == KEY_MAIN:
                self.active_profile_id = None
                self.router.show("main")
                self.layout.sidebar.clear_selection()
            elif key == KEY_SETTINGS:
                self.active_profile_id = None
                self.router.show("settings")
                self.layout.sidebar.clear_selection()
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

    # --- Настройки ---

    def save_settings_now(self) -> None:
        try:
            save_settings(self.settings)
        except Exception as exc:
            logger.error("Не удалось сохранить настройки: %r", exc)
        self.refresh_monitor_config()

    def refresh_sidebar(self) -> None:
        self.layout.sidebar.rebuild_profiles(self.settings.profiles)
        self.refresh_monitor_config()

    # --- Мониторинг источника и уведомления ---

    def refresh_monitor_config(self) -> None:
        """Пересинхронизирует монитор с текущими настройками.

        Вызывается после любого изменения настроек или списка
        профилей. Монитор либо стартует, либо останавливается —
        сам он по настройкам не «догадывается».
        """
        monitor = getattr(self, "monitor", None)
        if monitor is None:
            return

        try:
            monitor.configure(
                self.settings.profiles, self.settings,
            )
            if self.settings.notifications_enabled:
                self._ensure_tray_for_monitor()
                monitor.start()
            else:
                monitor.stop()
        except Exception as exc:
            logger.error(
                "Не удалось переконфигурировать монитор: %r",
                exc, exc_info=True,
            )

    def _ensure_tray_for_monitor(self) -> None:
        """Трей нужен как фолбэк, если UI-тост недоступен.

        При штатной работе уведомления показывает собственное
        окно (`ui/components/toast.py`). Иконка в трее поднимается
        только для режима «сворачивать в трей» — иначе не нужна.
        """
        if self._tray.is_active:
            return
        if not self.settings.minimize_to_tray:
            return
        if not self._tray.start():
            logger.debug("Трей недоступен")

    def _is_profile_busy(self, _profile_id: str) -> bool:
        """Идёт ли сейчас копирование/восстановление.

        Пока идёт длительная операция, опрос источника
        пропускается целиком: не мешаем диску и не показываем
        уведомление о том, что пользователь только что копирует.
        Следующий цикл подхватит изменения.
        """
        return (
            self.copy_service.is_running
            or self.restore_service.is_running
        )

    def reset_monitor_profile(self, profile_id: str) -> None:
        """Сбрасывает базу мониторинга профиля после копирования."""
        monitor = getattr(self, "monitor", None)
        if monitor is None:
            return
        try:
            monitor.reset_profile(profile_id)
        except Exception as exc:
            logger.debug(
                "reset_monitor_profile(%r): %r", profile_id, exc,
            )

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

    def refresh_current_profile_view(self) -> None:
        """Обновляет текущий ProfileView (например, метку версии)."""
        if self.active_profile_id is None:
            return
        view = self.router.get_view("profile")
        if view is None:
            return
        on_show = getattr(view, "on_show", None)
        if callable(on_show):
            try:
                on_show()
            except Exception as exc:
                logger.debug("on_show ProfileView: %r", exc)

    # --- Автопроверка при старте ---

    def _run_startup_check(self) -> None:
        if self._closing:
            return
        self.startup_checker.start(
            self.settings.profiles,
            run_on_restored=self.settings.run_autocheck_on_restored,
        )

    # --- Проверка + запуск (кнопка ▶) ---

    def run_with_check(self, pid: str) -> None:
        profile = self.profile_actions.find(pid)
        if profile is None:
            return

        if self.copy_service.is_running:
            self.set_status("Копирование уже выполняется")
            return

        if self.restore_service.is_running:
            self.set_status("Восстановление уже выполняется")
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

        if not self.ensure_disk_space(
            profile.source, profile.destination,
            profile.create_backup,
        ):
            return

        self.set_status_progress("Копирование…", 0.0)

        started = self.start_copy_with_ui(
            source=profile.source,
            destination=profile.destination,
            create_backup=profile.create_backup,
            hash_cache_enabled=self.settings.hash_cache_enabled,
            mirror_mode=profile.mirror_mode,
            profile_name=profile.display_name,
            is_startup_check=False,
            on_progress=self._on_run_check_progress,
            on_done=lambda r, p=profile: self._on_run_check_done(r, p),
            on_error=self._on_run_check_error,
        )
        if not started:
            self.set_status("Не удалось запустить копирование")

    def _on_run_check_progress(self, progress) -> None:
        if progress.phase == PHASE_SAVE_SCAN:
            self.set_status_progress(
                f"Сканирование: "
                f"{progress.processed}/{progress.total}",
                progress.percent / 100.0,
            )
            return
        if progress.phase == PHASE_SAVE_STORE:
            self.set_status_progress(
                f"Сохранение в хранилище: "
                f"{progress.processed}/{progress.total}",
                progress.percent / 100.0,
            )
            return

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

        copy_text = format_copy_status(result)
        copy_text += format_mirror_suffix(result)

        if result.errors > 0:
            self.set_status_progress(copy_text, None)
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

        profile.touch()
        save_settings(self.settings)
        self.reset_monitor_profile(profile.id)

        if not profile.exe_relative:
            self.set_status_progress(
                f"{copy_text}  ·  Запускаемое приложение не указано",
                None,
            )
            return

        full = profile.exe_full_path()
        if not full or not Path(full).is_file():
            self.set_status_progress(
                f"{copy_text}  ·  Файл приложения не найден",
                None,
            )
            return

        from services.system.launcher import LaunchError, launch_exe
        try:
            launch_exe(full)
        except LaunchError as exc:
            self.set_status_progress(
                f"{copy_text}  ·  Ошибка запуска",
                None,
            )
            show_error(
                self,
                "Ошибка запуска",
                str(exc),
                parent_visible=self.is_parent_visible(),
            )
            return

        self.set_status_progress(
            f"{copy_text}  ·  Запущено: {Path(full).name}",
            None,
        )

    def _on_run_check_error(self, message: str) -> None:
        self.set_status_progress(f"Ошибка: {message}", None)
        show_error(
            self,
            "Ошибка копирования",
            message,
            parent_visible=self.is_parent_visible(),
        )

    # --- Действия с профилями ---

    def _on_add_profile(self) -> None:
        self.profile_actions.add()

    def _on_profile_context(
        self, pids: list[str], x: int, y: int,
    ) -> None:
        """ПКМ по профилю (или группе выделенных).

        Если выделен один — полное меню действий.
        Если несколько — только «Удалить N профилей».
        """
        if not pids:
            return

        menu = ContextMenu(self)

        if len(pids) == 1:
            pid = pids[0]
            if self.profile_actions.find(pid) is None:
                return
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
                lambda: self.profile_actions.delete_many([pid]),
                icon="🗑",
                danger=True,
            )
        else:
            label = self._delete_many_label(len(pids))
            menu.add_item(
                label,
                lambda: self.profile_actions.delete_many(pids),
                icon="🗑",
                danger=True,
            )

        menu.show(x, y)

    @staticmethod
    def _delete_many_label(n: int) -> str:
        if n % 10 == 1 and n % 100 != 11:
            word = "профиль"
        elif 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
            word = "профиля"
        else:
            word = "профилей"
        return f"Удалить {n} {word}"

    def _on_run_profile(self, pid: str) -> None:
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

    def _on_close_request(self, force: bool = False) -> None:
        if self._closing:
            return

        # Сворачивание в трей по X (если не принудительный выход).
        if not force and self.settings.minimize_to_tray:
            if self._closing:
                return
            self._hide_to_tray()
            return

        if self.settings.confirm_on_exit and not force:
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
        monitor = getattr(self, "monitor", None)
        if monitor is not None:
            monitor.stop()
        self._tray.stop()
        self.startup_checker.cancel()
        try:
            if self.copy_service.is_running:
                self.copy_service.cancel()
            if self.restore_service.is_running:
                self.restore_service.cancel()
            self._save_geometry()
            save_settings(self.settings)
        except Exception as exc:
            logger.error("Ошибка сохранения при закрытии: %r", exc)
        self.destroy()
