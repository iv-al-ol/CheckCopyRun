"""Главное окно приложения."""

from __future__ import annotations

import ctypes
import re
from pathlib import Path

import customtkinter as ctk

from config.constants import (
    APP_TITLE,
    DEFAULT_PROFILE_NAME_PREFIX,
    THEME_DEFAULT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from core.models import AppSettings, Profile
from core.paths import get_asset_path
from core.settings_store import load_settings, save_settings
from services.copy_service import CopyResult, CopyService
from ui.components.context_menu import ContextMenu
from ui.components.icon_picker import pick_icon
from ui.components.status_bar import StatusBar
from ui.dialogs import ask_yes_no
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
from ui.views.main_view import MainView
from ui.views.profile_view import ProfileView
from ui.views.settings_view import SettingsView
from utils.logger import get_logger

logger = get_logger(__name__)

# Регулярка с группами: width, height, x, y.
_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")

_STARTUP_CHECK_DELAY_MS = 700
_STARTUP_NEXT_DELAY_MS = 80

# Задержка перед первичной фиксацией last_visible_rect — чтобы
# окно успело получить финальную геометрию от оконного менеджера.
_INITIAL_RECT_DELAY_MS = 80

# Минимально видимая часть окна на экране при восстановлении.
_MIN_VISIBLE_PX = 100

# Индексы GetSystemMetrics для виртуального экрана (все мониторы).
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

# Маркер свёрнутого окна Windows: координаты (-32000, -32000).
_MINIMIZED_COORD_MARKER = -30000


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.settings: AppSettings = load_settings()
        apply_theme(self.settings.theme or THEME_DEFAULT)

        self.title(APP_TITLE)
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self._active_profile_id: str | None = None
        self._icon_photo = None
        self._closing = False

        # Последняя видимая геометрия окна. Используется диалогами,
        # когда окно свёрнуто или скрыто в трей: они открываются
        # по центру монитора, где окно было в последний раз.
        self._last_visible_rect: tuple[int, int, int, int] | None = None

        self._startup_queue: list[Profile] = []
        self._startup_total = 0
        self._startup_index = 0
        self._startup_running = False

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

        # Отслеживаем перемещение / изменение размера окна. Плюс
        # первичная фиксация через небольшую задержку — до неё
        # winfo_* могут отдавать промежуточные значения.
        self.bind("<Configure>", self._on_window_configure, add="+")
        self.after(_INITIAL_RECT_DELAY_MS, self._on_window_configure)

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

    # --- DPI и виртуальный экран ---

    def _get_dpi_scaling(self) -> float:
        try:
            value = ctk.ScalingTracker.get_window_dpi_scaling(self)
            if value and value > 0:
                return float(value)
        except Exception as exc:
            logger.debug("ScalingTracker недоступен: %r", exc)
        return 1.0

    def _get_virtual_screen_physical(
        self,
    ) -> tuple[int, int, int, int] | None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
        except OSError as exc:
            logger.debug("user32 недоступен: %r", exc)
            return None

        try:
            x = int(user32.GetSystemMetrics(_SM_XVIRTUALSCREEN))
            y = int(user32.GetSystemMetrics(_SM_YVIRTUALSCREEN))
            w = int(user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN))
            h = int(user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN))
        except Exception as exc:
            logger.debug("GetSystemMetrics(VIRTUALSCREEN): %r", exc)
            return None

        if w <= 0 or h <= 0:
            return None
        return x, y, w, h

    # --- Геометрия ---

    def _restore_or_default_geometry(self) -> None:
        saved = self.settings.window_geometry
        if saved and _GEOMETRY_RE.match(saved):
            if self._try_restore_geometry(saved):
                return
            logger.debug(
                "Сохранённая геометрия %r не применена — дефолт",
                saved,
            )

        self._apply_default_geometry()

    def _apply_default_geometry(self) -> None:
        w = WINDOW_MIN_WIDTH
        h = WINDOW_MIN_HEIGHT

        scaling = self._get_dpi_scaling() or 1.0
        try:
            sw = int(self.winfo_screenwidth() / scaling)
            sh = int(self.winfo_screenheight() / scaling)
        except Exception as exc:
            logger.debug("размер экрана недоступен: %r", exc)
            sw, sh = w, h

        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _try_restore_geometry(self, geometry: str) -> bool:
        parsed = self._parse_geometry(geometry)
        if parsed is None:
            return False

        w, h, x, y = parsed

        if w < WINDOW_MIN_WIDTH or h < WINDOW_MIN_HEIGHT:
            logger.debug(
                "Сохранённый размер %dx%d меньше минимального",
                w, h,
            )
            return False

        if not self._is_inside_virtual_screen(x, y, w, h):
            logger.debug(
                "Окно %dx%d+%d+%d вне видимой области", w, h, x, y,
            )
            return False

        try:
            self.geometry(geometry)
            logger.debug("Восстановлена геометрия: %r", geometry)
            return True
        except Exception as exc:
            logger.debug(
                "geometry(%r) не сработал: %r", geometry, exc,
            )
            return False

    def _is_inside_virtual_screen(
        self, x: int, y: int, w: int, h: int,
    ) -> bool:
        scaling = self._get_dpi_scaling() or 1.0

        vs = self._get_virtual_screen_physical()
        if vs is None:
            try:
                sw_phys = self.winfo_screenwidth()
                sh_phys = self.winfo_screenheight()
            except Exception as exc:
                logger.debug("размер экрана недоступен: %r", exc)
                return True
            vs_x, vs_y, vs_w, vs_h = 0, 0, sw_phys, sh_phys
        else:
            vs_x, vs_y, vs_w, vs_h = vs

        vs_x = int(vs_x / scaling)
        vs_y = int(vs_y / scaling)
        vs_w = int(vs_w / scaling)
        vs_h = int(vs_h / scaling)

        vs_right = vs_x + vs_w
        vs_bottom = vs_y + vs_h

        right = x + w
        bottom = y + h

        overlap_w = min(right, vs_right) - max(x, vs_x)
        overlap_h = min(bottom, vs_bottom) - max(y, vs_y)

        return (
            overlap_w >= _MIN_VISIBLE_PX
            and overlap_h >= _MIN_VISIBLE_PX
        )

    @staticmethod
    def _parse_geometry(
        geometry: str,
    ) -> tuple[int, int, int, int] | None:
        match = _GEOMETRY_RE.match(geometry)
        if not match:
            return None
        try:
            w = int(match.group(1))
            h = int(match.group(2))
            x = int(match.group(3))
            y = int(match.group(4))
        except (TypeError, ValueError) as exc:
            logger.debug("parse_geometry: %r", exc)
            return None
        return w, h, x, y

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

        scaling = self._get_dpi_scaling() or 1.0
        lw = int(round(w / scaling))
        lh = int(round(h / scaling))
        lx = int(round(x / scaling))
        ly = int(round(y / scaling))

        self.settings.window_geometry = f"{lw}x{lh}+{lx}+{ly}"

    # --- Позиция окна для диалогов ---

    def _on_window_configure(self, event=None) -> None:
        """Обновляет _last_visible_rect при перемещении / ресайзе.

        Сохраняем только когда окно в нормальном состоянии: при
        минимизации Windows ставит координаты-маркер (-32000).
        """
        if event is not None and getattr(event, "widget", None) is not self:
            return

        try:
            state = self.state()
        except Exception as exc:
            logger.debug("state(): %r", exc)
            return

        if state != "normal":
            return

        try:
            x = int(self.winfo_rootx())
            y = int(self.winfo_rooty())
            w = int(self.winfo_width())
            h = int(self.winfo_height())
        except Exception as exc:
            logger.debug("геометрия last_visible_rect: %r", exc)
            return

        if w <= 1 or h <= 1:
            return

        if x <= _MINIMIZED_COORD_MARKER or y <= _MINIMIZED_COORD_MARKER:
            return

        self._last_visible_rect = (x, y, x + w, y + h)

    def get_last_visible_rect(
        self,
    ) -> tuple[int, int, int, int] | None:
        """Последний видимый прямоугольник окна в координатах Tk.

        Используется диалогами, когда окно свёрнуто или скрыто в
        трей: чтобы открыться по центру монитора, на котором окно
        было в последний раз. Возвращает None, если координаты ещё
        не зафиксированы.
        """
        return self._last_visible_rect

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

    def open_profile(self, pid: str) -> None:
        self._on_sidebar_select(profile_key(pid))

    def show_main(self) -> None:
        self._on_sidebar_select(KEY_MAIN)

    # --- Публичное API для views ---

    def save_settings_now(self) -> None:
        try:
            save_settings(self.settings)
        except Exception as exc:
            logger.error("Не удалось сохранить настройки: %r", exc)

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

            self._startup_queue.clear()
            self._startup_running = False

            self.settings = AppSettings()
            apply_theme(self.settings.theme or THEME_DEFAULT)
            save_settings(self.settings)

            self._active_profile_id = None
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
                        logger.debug("on_show SettingsView: %r", exc)

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

        candidates = [
            p for p in self.settings.profiles
            if p.check_on_startup and p.has_source_and_dest()
        ]
        if not candidates:
            return

        candidates.sort(
            key=lambda p: p.last_used_at or "", reverse=True,
        )

        self._startup_queue = list(candidates)
        self._startup_total = len(candidates)
        self._startup_index = 0
        self._startup_running = True

        logger.info(
            "Автопроверка: %d профил(ей) в очереди", self._startup_total,
        )
        self._process_next_startup()

    def _process_next_startup(self) -> None:
        if self._closing:
            return

        if not self._startup_queue:
            self._startup_running = False
            self.set_status_progress("Автопроверка завершена", None)
            logger.info("Автопроверка: всё завершено")
            self.refresh_main_view()
            return

        profile = self._startup_queue.pop(0)
        self._startup_index += 1

        header = (
            f"Автопроверка {self._startup_index}/{self._startup_total}: "
            f"{profile.display_name}"
        )
        self.set_status_progress(header, 0.0)

        started = self.copy_service.start(
            source=profile.source,
            destination=profile.destination,
            create_backup=profile.create_backup,
            on_progress=self._on_startup_progress,
            on_done=lambda r, p=profile: self._on_startup_done(r, p),
            on_error=lambda msg, p=profile: self._on_startup_error(
                msg, p,
            ),
        )
        if not started:
            logger.warning(
                "Автопроверка: профиль %s пропущен (start=False)",
                profile.display_name,
            )
            self.after(
                _STARTUP_NEXT_DELAY_MS, self._process_next_startup,
            )

    def _on_startup_progress(self, progress) -> None:
        header = (
            f"Автопроверка {self._startup_index}/{self._startup_total}"
        )
        self.set_status_progress(
            header, progress.percent / 100.0,
        )

    def _on_startup_done(
        self, result: CopyResult, profile: Profile,
    ) -> None:
        if self._closing:
            return

        if result.cancelled:
            logger.info("Автопроверка прервана")
            self._startup_queue.clear()
            self._startup_running = False
            return

        profile.touch()
        save_settings(self.settings)

        logger.info(
            "Автопроверка %s: скопировано %d, пропущено %d, "
            "ошибок %d",
            profile.display_name,
            result.copied, result.skipped, result.errors,
        )

        self.after(
            _STARTUP_NEXT_DELAY_MS, self._process_next_startup,
        )

    def _on_startup_error(
        self, message: str, profile: Profile,
    ) -> None:
        if self._closing:
            return

        logger.error(
            "Автопроверка %s: %s", profile.display_name, message,
        )

        self.after(
            _STARTUP_NEXT_DELAY_MS, self._process_next_startup,
        )

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
        self.refresh_main_view()
        self._on_sidebar_select(profile_key(profile.id))
        self.set_status(f"Создан {profile.display_name}")

    def _on_run_profile(self, pid: str) -> None:
        profile = self._find_profile(pid)
        if profile is None:
            self.set_status(f"Профиль {pid[:8]} не найден")
            return

        from services.launcher import LaunchError, launch_exe
        try:
            full = profile.exe_full_path()
            launch_exe(full)
        except LaunchError as exc:
            self.set_status(f"Ошибка запуска: {exc}")
            return

        profile.touch()
        save_settings(self.settings)
        self.set_status(f"Запущено: {profile.display_name}")

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
        self.refresh_main_view()
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
        self.refresh_main_view()
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
        self.refresh_main_view()

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
        full = profile.exe_source_path()
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
        if self._closing:
            return

        if self.settings.confirm_on_exit:
            confirmed = ask_yes_no(
                self,
                "Закрытие приложения",
                "Закрыть CheckCopyRun?",
                yes_text="Закрыть",
                no_text="Отмена",
                parent_visible=self._parent_visible(),
            )
            if not confirmed:
                return

        self._closing = True
        self._startup_queue.clear()
        try:
            if self.copy_service.is_running:
                self.copy_service.cancel()
            self._save_geometry()
            self.settings.last_view = self.router.current or KEY_MAIN
            save_settings(self.settings)
        except Exception as exc:
            logger.error("Ошибка сохранения при закрытии: %r", exc)
        self.destroy()
