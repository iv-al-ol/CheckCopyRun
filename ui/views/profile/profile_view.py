"""Экран профиля: связывает шапку, форму и действия.

Нижняя зона:
  • Метка текущей версии файлов (над первым разделителем,
    полужирный шрифт того же размера/цвета, что и раньше).
    Расчёт метки выполняется в фоновом потоке — для папок с
    большим числом файлов UI не блокируется. Пока идёт расчёт,
    показывается placeholder «Определение версии…». Защита от
    гонок: счётчик _label_gen — если пользователь переключился
    на другой профиль, устаревший результат отбрасывается.
  • Ряд действий: Копировать / Запустить приложение / Резервные
    копии.
  • Ряд служебных: Сменить иконку / Переименовать / Сбросить
    настройки / Удалить.

Предупреждение при снятии флажка «Создавать резервные копии»
показывается один раз — за всё время жизни профиля. Флаг
profile.create_backup_warned сохраняется в settings.dat.
"""

from __future__ import annotations

import os
import threading

import customtkinter as ctk

from config.constants import (
    DEFAULT_PROFILE_ICON,
    PROFILE_ACTION_BAR_PADY_BOTTOM,
    PROFILE_ACTION_BAR_PADY_TOP,
    PROFILE_ACTION_BUTTON_HEIGHT,
    PROFILE_UTILITY_BAR_PADY_BOTTOM,
    PROFILE_UTILITY_BAR_PADY_TOP,
    PROFILE_UTILITY_BUTTON_HEIGHT,
    SEPARATOR_PADY,
)
from core.models import Profile
from core.settings_store import save_settings
from services.cas import destination_state
from services.restore.restore_service import RestoreResult
from ui.components.button import (
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.components.scrollable import AutoHideScrollableFrame
from ui.components.separator import make_separator
from ui.dialogs import ask_yes_no, show_error
from ui.dialogs.backup_list import open_backup_list
from ui.fonts import get_font
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

_BUTTON_FONT_SIZE = 13
_BUTTON_PADDING = 36
_BUTTON_MIN_WIDTH = 100
_BUTTON_MAX_WIDTH = 280

_VERSION_FONT_SIZE = 12
_VERSION_PLACEHOLDER = "Определение версии…"

_ACTION_LABEL_COPY = "Копировать"
_ACTION_LABEL_RUN = "Запустить приложение"
_ACTION_LABEL_BACKUPS = "Резервные копии"

_UTILITY_LABELS: tuple[str, ...] = (
    "Сменить иконку",
    "Переименовать",
    "Сбросить настройки",
    "Удалить",
)


def _button_width_for(text: str) -> int:
    """Ширина кнопки под текст + отступы."""
    try:
        font = get_font(_BUTTON_FONT_SIZE)
        measured = int(font.measure(text))
    except Exception as exc:
        logger.debug("font.measure недоступен: %r", exc)
        measured = len(text) * 9
    width = measured + _BUTTON_PADDING
    return max(_BUTTON_MIN_WIDTH, min(_BUTTON_MAX_WIDTH, width))


class ProfileView(BaseView):
    """Форма профиля. Один экземпляр, переключается через set_profile."""

    def __init__(self, master, window):
        super().__init__(master, window)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._profile_id: str | None = None
        self._busy = False
        self._label_gen: int = 0

        self._ideal_button_width = max(
            _button_width_for(_ACTION_LABEL_COPY),
            _button_width_for(_ACTION_LABEL_RUN),
            _button_width_for(_ACTION_LABEL_BACKUPS),
        )
        self._current_button_width = self._ideal_button_width

        self._ideal_utility_width = max(
            _UTILITY_BUTTON_WIDTH,
            *(_button_width_for(t) for t in _UTILITY_LABELS),
        )
        self._current_utility_width = self._ideal_utility_width

        self._utility_buttons: list[StyledButton] = []

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

        self._scroll = AutoHideScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
        )
        self._scroll.grid(
            row=0, column=0, sticky="nsew",
        )
        self._scroll.grid_columnconfigure(0, weight=1)

        self._header = ProfileHeader(self._scroll)
        self._header.grid(
            row=0, column=0, sticky="ew",
            padx=24, pady=(20, 12),
        )

        self._form = ProfileForm(
            self._scroll,
            on_pick_source=self._path_controller.pick_source,
            on_open_source=self._on_open_source_folder,
            on_pick_destination=self._path_controller.pick_destination,
            on_open_destination=self._on_open_destination_folder,
            on_pick_exe=self._path_controller.pick_exe,
            on_backup_toggle=self._on_backup_toggle,
            on_run_after_toggle=self._on_run_after_toggle,
            on_check_on_startup_toggle=self._on_check_on_startup_toggle,
            on_mirror_toggle=self._on_mirror_toggle,
            on_notify_changes_toggle=self._on_notify_changes_toggle,
            on_notify_message_toggle=self._on_notify_message_toggle,
        )
        self._form.grid(
            row=1, column=0, sticky="ew",
            padx=24, pady=(0, 12),
        )

        self._build_version_label()
        self._build_top_separator()
        self._build_action_bar()
        self._build_bottom_separator()
        self._build_utility_bar()

    # --- Публичное ---

    def set_profile(self, pid: str) -> None:
        self._profile_id = pid
        self._reload_from_profile()

    def on_show(self) -> None:
        self._reload_from_profile()

    # --- Метка версии ---

    def _build_version_label(self) -> None:
        self._version_label = ctk.CTkLabel(
            self,
            text="",
            anchor="w",
            justify="left",
            font=get_font(_VERSION_FONT_SIZE, "bold"),
            text_color=("gray40", "gray60"),
        )
        self._version_label.grid(
            row=1, column=0, sticky="ew",
            padx=24, pady=(0, 4),
        )

    def _update_version_label(
        self, profile: Profile | None,
    ) -> None:
        """Запускает расчёт метки версии в фоновом потоке.

        Немедленно: обнуляет счётчик поколений и показывает
        placeholder. По завершении фона — обновляет текст, если
        поколение не изменилось.
        """
        self._label_gen += 1
        gen = self._label_gen

        if profile is None or not profile.destination:
            self._set_version_label_text(gen, "")
            return

        dest = profile.destination

        # Placeholder — чтобы не показывать устаревшую метку
        # от предыдущего профиля и не пустоту.
        try:
            self._version_label.configure(
                text=_VERSION_PLACEHOLDER,
            )
        except Exception as exc:
            logger.debug(
                "configure placeholder: %r", exc,
            )

        window = self.window

        def worker() -> None:
            try:
                text = destination_state.build_label(dest)
            except Exception as exc:
                logger.debug("build_label: %r", exc)
                text = ""
            try:
                window.after(
                    0,
                    lambda: self._apply_label(gen, text),
                )
            except Exception as exc:
                logger.debug(
                    "after для метки версии: %r", exc,
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="VersionLabelWorker",
        ).start()

    def _apply_label(self, gen: int, text: str) -> None:
        """Применяет результат из фонового потока.

        Результат отбрасывается, если:
          • за это время было запущено новое поколение
            (_label_gen изменился);
          • виджет уже уничтожен.
        """
        if gen != self._label_gen:
            return
        try:
            if not self.winfo_exists():
                return
            self._version_label.configure(text=text)
        except Exception as exc:
            logger.debug("_apply_label: %r", exc)

    def _set_version_label_text(
        self, gen: int, text: str,
    ) -> None:
        if gen != self._label_gen:
            return
        try:
            self._version_label.configure(text=text)
        except Exception as exc:
            logger.debug(
                "configure version_label: %r", exc,
            )

    # --- Разделители ---

    def _build_top_separator(self) -> None:
        sep = make_separator(self)
        sep.grid(
            row=2, column=0, sticky="ew",
            padx=24, pady=SEPARATOR_PADY,
        )

    def _build_bottom_separator(self) -> None:
        sep = make_separator(self)
        sep.grid(
            row=4, column=0, sticky="ew",
            padx=24, pady=SEPARATOR_PADY,
        )

    # --- Ряд действий ---

    def _build_action_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(
            row=3, column=0, sticky="ew",
            padx=24,
            pady=(
                PROFILE_ACTION_BAR_PADY_TOP,
                PROFILE_ACTION_BAR_PADY_BOTTOM,
            ),
        )

        bar.grid_columnconfigure(0, weight=0)
        bar.grid_columnconfigure(1, weight=0)
        bar.grid_columnconfigure(2, weight=1)
        bar.grid_columnconfigure(3, weight=0)

        self._action_bar = bar
        w = self._ideal_button_width

        self._copy_btn = StyledButton(
            bar, text=_ACTION_LABEL_COPY,
            variant=VARIANT_PRIMARY,
            width=w,
            height=PROFILE_ACTION_BUTTON_HEIGHT,
            command=self._process_controller.copy,
        )
        self._copy_btn.grid(
            row=0, column=0, padx=(0, _BUTTON_GAP),
        )

        self._run_btn = StyledButton(
            bar, text=_ACTION_LABEL_RUN,
            variant=VARIANT_SECONDARY,
            width=w,
            height=PROFILE_ACTION_BUTTON_HEIGHT,
            command=self._process_controller.run,
        )
        self._run_btn.grid(row=0, column=1)

        self._backups_btn = StyledButton(
            bar, text=_ACTION_LABEL_BACKUPS,
            variant=VARIANT_SECONDARY,
            width=w,
            height=PROFILE_ACTION_BUTTON_HEIGHT,
            command=self._on_open_backups,
        )
        self._backups_btn.grid(row=0, column=3)

        bar.bind(
            "<Configure>", self._on_action_bar_configure, add="+",
        )

    def _on_action_bar_configure(self, event) -> None:
        try:
            bar_w = int(event.width)
        except Exception as exc:
            logger.debug("event.width: %r", exc)
            return

        if bar_w <= 1:
            return

        min_w = _BUTTON_MIN_WIDTH
        ideal = self._ideal_button_width
        gap = _BUTTON_GAP
        needed_ideal = ideal * 3 + 2 * gap

        if bar_w >= needed_ideal:
            new_w = ideal
        else:
            available = bar_w - 2 * gap
            if available < min_w * 3:
                new_w = min_w
            else:
                new_w = available // 3

        if new_w == self._current_button_width:
            return

        self._current_button_width = new_w

        for btn in (self._copy_btn, self._run_btn, self._backups_btn):
            try:
                btn.configure(width=new_w)
            except Exception as exc:
                logger.debug("configure(width) кнопки: %r", exc)

    # --- Ряд служебных кнопок ---

    def _build_utility_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(
            row=5, column=0, sticky="ew",
            padx=24,
            pady=(
                PROFILE_UTILITY_BAR_PADY_TOP,
                PROFILE_UTILITY_BAR_PADY_BOTTOM,
            ),
        )

        self._utility_bar = bar
        w = self._ideal_utility_width

        commands = (
            self._on_change_icon,
            self._on_rename,
            self._on_reset,
            self._on_delete,
        )

        self._utility_buttons = []
        last_idx = len(_UTILITY_LABELS) - 1

        for idx, (label, cmd) in enumerate(
            zip(_UTILITY_LABELS, commands)
        ):
            btn = StyledButton(
                bar, text=label,
                variant=VARIANT_SECONDARY,
                width=w,
                height=PROFILE_UTILITY_BUTTON_HEIGHT,
                command=cmd,
            )
            btn.grid(
                row=0, column=idx,
                padx=(0, _BUTTON_GAP if idx < last_idx else 0),
            )
            self._utility_buttons.append(btn)

        bar.bind(
            "<Configure>", self._on_utility_bar_configure, add="+",
        )

    def _on_utility_bar_configure(self, event) -> None:
        try:
            bar_w = int(event.width)
        except Exception as exc:
            logger.debug("event.width: %r", exc)
            return

        if bar_w <= 1:
            return

        count = len(self._utility_buttons)
        if count == 0:
            return

        min_w = _BUTTON_MIN_WIDTH
        ideal = self._ideal_utility_width
        gap = _BUTTON_GAP

        needed_ideal = ideal * count + gap * (count - 1)

        if bar_w >= needed_ideal:
            new_w = ideal
        else:
            available = bar_w - gap * (count - 1)
            if available < min_w * count:
                new_w = min_w
            else:
                new_w = available // count

        if new_w == self._current_utility_width:
            return

        self._current_utility_width = new_w

        for btn in self._utility_buttons:
            try:
                btn.configure(width=new_w)
            except Exception as exc:
                logger.debug("configure(width) кнопки: %r", exc)

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
                mirror_mode=False,
                notify_on_changes=True,
                notify_on_message=True,
            )
            self._form.update_open_buttons(
                source_enabled=False,
                destination_enabled=False,
            )
            self._update_version_label(None)
            self._after_layout()
            return

        if not profile.exe_relative and profile.run_after_copy:
            profile.run_after_copy = False
            save_settings(self.window.settings)

        self._header.update(profile, profile_subtitle(profile))
        self._form.update_values(
            source=profile.source,
            destination=profile.destination,
            exe_name=_exe_name(profile),
            create_backup=profile.create_backup,
            run_after_copy=profile.run_after_copy,
            check_on_startup=profile.check_on_startup,
            mirror_mode=profile.mirror_mode,
            notify_on_changes=profile.notify_on_changes,
            notify_on_message=profile.notify_on_message,
        )
        self._update_open_buttons(profile)
        self._update_buttons_state(profile)
        self._update_version_label(profile)
        self._after_layout()

    def _after_layout(self) -> None:
        try:
            self._scroll.check_scroll()
            self.after(60, self._check_scroll_now)
            self.after(250, self._check_scroll_now)
        except Exception as exc:
            logger.debug("после раскладки: %r", exc)

    def _check_scroll_now(self) -> None:
        try:
            self._scroll.check_scroll_now()
        except Exception as exc:
            logger.debug("check_scroll_now: %r", exc)

    def _update_open_buttons(self, profile: Profile) -> None:
        self._form.update_open_buttons(
            source_enabled=bool(profile.source),
            destination_enabled=bool(profile.destination),
        )

    def _update_buttons_state(self, profile: Profile) -> None:
        if self._busy:
            self._copy_btn.configure(state="disabled")
            self._run_btn.configure(state="disabled")
            return

        conflict = path_conflict_error(
            profile.source, profile.destination,
        )
        if conflict:
            self._copy_btn.configure(state="disabled")
            self._run_btn.configure(state="disabled")
            return

        self._copy_btn.configure(
            state="normal" if profile.can_copy() else "disabled",
        )
        self._run_btn.configure(
            state="normal" if profile.can_run() else "disabled",
        )

    # --- Резервные копии и восстановление ---

    def _on_open_backups(self) -> None:
        profile = self._profile()
        if profile is None:
            return

        open_backup_list(
            parent=self.window,
            profile_name=profile.display_name,
            destination=profile.destination,
            parent_visible=True,
            on_restore=lambda path, p=profile: (
                self._on_restore_from_backup(path, p)
            ),
        )

    def _on_restore_from_backup(
        self, backup_state_ref: str, profile: Profile,
    ) -> None:
        if self._busy:
            show_error(
                self.window,
                "Нельзя восстановить",
                "Дождитесь завершения текущей операции.",
            )
            return

        started = self.window.start_restore_with_ui(
            backup_state_ref=backup_state_ref,
            destination=profile.destination,
            profile_name=profile.display_name,
            on_done=lambda r: self._on_restore_done(r, profile),
        )
        if not started:
            show_error(
                self.window,
                "Не удалось запустить восстановление",
                "Операция не начата. Подробности — в логе.",
            )

    def _on_restore_done(
        self, result: RestoreResult, profile: Profile,
    ) -> None:
        self._reload_from_profile()

        if result.cancelled:
            return
        if result.errors > 0:
            show_error(
                self.window,
                "Восстановление с ошибками",
                (
                    f"Ошибок: {result.errors}. "
                    f"Подробности — в логе."
                ),
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

        new_value = self._form.create_backup

        if (
            profile.create_backup
            and not new_value
            and not profile.create_backup_warned
        ):
            confirmed = ask_yes_no(
                self.window,
                "Отключение резервного копирования",
                (
                    "Отключить создание резервных копий?\n\n"
                    "Новые резервные копии создаваться не будут. "
                    "Существующие останутся — вы сможете "
                    "восстановиться из них.\n\n"
                    "Продолжить?"
                ),
                yes_text="Отключить",
                no_text="Отмена",
                parent_visible=True,
            )
            if not confirmed:
                self._form.set_create_backup(True)
                return
            profile.create_backup_warned = True

        profile.create_backup = new_value
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

    def _on_mirror_toggle(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        profile.mirror_mode = self._form.mirror_mode
        save_settings(self.window.settings)
        state = "включён" if profile.mirror_mode else "выключен"
        self.window.set_status(f"Режим зеркала {state}")

    def _on_notify_changes_toggle(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        profile.notify_on_changes = self._form.notify_on_changes
        save_settings(self.window.settings)
        self.window.refresh_monitor_config()
        state = (
            "включены" if profile.notify_on_changes else "выключены"
        )
        self.window.set_status(
            f"Уведомления об изменениях файлов {state}",
        )

    def _on_notify_message_toggle(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        profile.notify_on_message = self._form.notify_on_message
        save_settings(self.window.settings)
        self.window.refresh_monitor_config()
        state = (
            "включены" if profile.notify_on_message else "выключены"
        )
        self.window.set_status(
            f"Уведомления о сообщении источника {state}",
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
        self.window.profile_actions.delete_many([profile.id])

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
