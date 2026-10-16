"""Экран профиля: настройка source/destination/exe и действия."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from config.constants import (
    DEFAULT_PROFILE_ICON,
    PROFILE_BOTTOM_BAR_PADY_BOTTOM,
    PROFILE_BOTTOM_BAR_PADY_TOP,
    PROFILE_BOTTOM_BUTTON_HEIGHT,
    SEPARATOR_HEIGHT,
    SEPARATOR_PADY,
)
from core.models import Profile
from core.settings_store import get_icons_dir, save_settings
from services.copy_service import CopyResult
from services.icon_extractor import save_exe_icon
from services.launcher import LaunchError, launch_exe
from ui.components.button import (
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.components.icon_picker import pick_icon
from ui.dialogs import ask_yes_no, show_error
from ui.dialogs.profile_dialogs import (
    ask_delete_profile,
    ask_profile_name,
)
from ui.fonts import get_emoji_font, get_font
from ui.views.base_view import BaseView
from utils.logger import get_logger

logger = get_logger(__name__)

# --- Размеры элементов ---
_LABEL_FONT_SIZE = 13
_TITLE_FONT_SIZE = 20
_ICON_SIZE = 40
_ICON_CONTAINER_SIZE = _ICON_SIZE + 8

_MAX_SCALING_HINT = 4

_ENTRY_HEIGHT = 32
_BROWSE_WIDTH = 180

_ACTION_BUTTON_WIDTH = 220
_UTILITY_BUTTON_WIDTH = 160
_BUTTON_GAP = 8

_SEPARATOR_COLOR_DARK = "#4a4a4a"
_SEPARATOR_COLOR_LIGHT = "#b8b8b8"


def _separator_hex() -> str:
    if ctk.get_appearance_mode() == "Dark":
        return _SEPARATOR_COLOR_DARK
    return _SEPARATOR_COLOR_LIGHT


def _is_dir_empty(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            return next(it, None) is None
    except OSError as exc:
        logger.debug("scandir %s упал: %r", path, exc)
        return False


def _path_conflict_text(
    source: str, destination: str,
) -> str | None:
    """Возвращает текст конфликта source/destination или None.

    Конфликт — это любая из ситуаций:
      • пути совпадают;
      • destination внутри source;
      • source внутри destination.
    Все три ведут к рекурсивной перезаписи или копированию в себя.
    """
    if not source or not destination:
        return None

    try:
        src = Path(source).resolve()
        dst = Path(destination).resolve()
    except OSError as exc:
        logger.debug(
            "resolve путей %r / %r: %r", source, destination, exc,
        )
        return None

    if src == dst:
        return "Исходная и целевая директории совпадают"

    try:
        if src in dst.parents:
            return "Целевая директория находится внутри исходной"
        if dst in src.parents:
            return "Исходная директория находится внутри целевой"
    except Exception as exc:
        logger.debug("проверка вложенности путей: %r", exc)

    return None


class ProfileView(BaseView):
    """Форма профиля. Один экземпляр, переключается через set_profile."""

    def __init__(self, master, window):
        super().__init__(master, window)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._profile_id: str | None = None
        self._busy = False
        self._icon_ctk = None

        self._build_header()
        self._build_form()
        self._build_separator()
        self._build_bottom_bar()

    # --- Публичное ---

    def set_profile(self, pid: str) -> None:
        self._profile_id = pid
        self._reload_from_profile()

    def on_show(self) -> None:
        self._reload_from_profile()

    # --- Шапка ---

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(
            row=0, column=0, sticky="ew",
            padx=24, pady=(20, 12),
        )
        header.grid_columnconfigure(1, weight=1)

        icon_frame = ctk.CTkFrame(
            header,
            fg_color="transparent",
            width=_ICON_CONTAINER_SIZE,
            height=_ICON_CONTAINER_SIZE,
        )
        icon_frame.grid(
            row=0, column=0, rowspan=2, padx=(0, 12),
        )
        icon_frame.grid_propagate(False)

        self._icon_emoji_label = ctk.CTkLabel(
            icon_frame,
            text=DEFAULT_PROFILE_ICON,
            anchor="center",
            font=get_emoji_font(24),
        )
        self._icon_emoji_label.place(
            relx=0.5, rely=0.5, anchor="center",
        )

        self._icon_image_label = ctk.CTkLabel(
            icon_frame,
            text="",
            anchor="center",
        )

        self._name_label = ctk.CTkLabel(
            header,
            text="Профиль",
            anchor="w",
            font=get_font(_TITLE_FONT_SIZE, "bold"),
        )
        self._name_label.grid(row=0, column=1, sticky="w")

        self._subtitle_label = ctk.CTkLabel(
            header,
            text="",
            anchor="w",
            text_color=("gray40", "gray60"),
            font=get_font(11),
        )
        self._subtitle_label.grid(row=1, column=1, sticky="w")

    # --- Форма ---

    def _build_form(self) -> None:
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.grid(
            row=1, column=0, sticky="nsew",
            padx=24, pady=(0, 12),
        )
        form.grid_columnconfigure(0, weight=1)

        row = 0

        ctk.CTkLabel(
            form, text="Копировать из:", anchor="w",
            font=get_font(_LABEL_FONT_SIZE, "bold"),
        ).grid(
            row=row, column=0, columnspan=2,
            sticky="w", pady=(0, 4),
        )
        row += 1

        self._source_entry = ctk.CTkEntry(
            form, height=_ENTRY_HEIGHT, state="readonly",
        )
        self._source_entry.grid(
            row=row, column=0, sticky="ew", padx=(0, 8),
        )
        StyledButton(
            form, text="Выбрать директорию",
            variant=VARIANT_SECONDARY, width=_BROWSE_WIDTH,
            command=self._on_pick_source,
        ).grid(row=row, column=1, sticky="e")
        row += 1

        ctk.CTkLabel(
            form, text="Копировать в:", anchor="w",
            font=get_font(_LABEL_FONT_SIZE, "bold"),
        ).grid(
            row=row, column=0, columnspan=2,
            sticky="w", pady=(12, 4),
        )
        row += 1

        self._dest_entry = ctk.CTkEntry(
            form, height=_ENTRY_HEIGHT, state="readonly",
        )
        self._dest_entry.grid(
            row=row, column=0, sticky="ew", padx=(0, 8),
        )
        StyledButton(
            form, text="Выбрать директорию",
            variant=VARIANT_SECONDARY, width=_BROWSE_WIDTH,
            command=self._on_pick_destination,
        ).grid(row=row, column=1, sticky="e")
        row += 1

        ctk.CTkLabel(
            form, text="Запускаемое приложение:", anchor="w",
            font=get_font(_LABEL_FONT_SIZE, "bold"),
        ).grid(
            row=row, column=0, columnspan=2,
            sticky="w", pady=(12, 4),
        )
        row += 1

        self._exe_entry = ctk.CTkEntry(
            form, height=_ENTRY_HEIGHT, state="readonly",
        )
        self._exe_entry.grid(
            row=row, column=0, sticky="ew", padx=(0, 8),
        )
        StyledButton(
            form, text="Выбрать файл",
            variant=VARIANT_SECONDARY, width=_BROWSE_WIDTH,
            command=self._on_pick_exe,
        ).grid(row=row, column=1, sticky="e")
        row += 1

        self._backup_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            form,
            text="Создавать резервную копию изменённых файлов",
            variable=self._backup_var,
            command=self._on_backup_toggle,
        ).grid(
            row=row, column=0, columnspan=2,
            sticky="w", pady=(16, 4),
        )
        row += 1

        self._run_after_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            form,
            text="Запускать приложение после копирования",
            variable=self._run_after_var,
            command=self._on_run_after_toggle,
        ).grid(
            row=row, column=0, columnspan=2,
            sticky="w", pady=(4, 4),
        )
        row += 1

        self._check_on_startup_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            form,
            text="Проверять директорию при запуске CCRun",
            variable=self._check_on_startup_var,
            command=self._on_check_on_startup_toggle,
        ).grid(
            row=row, column=0, columnspan=2,
            sticky="w", pady=(4, 16),
        )
        row += 1

        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.grid(
            row=row, column=0, columnspan=2, sticky="w",
        )

        self._copy_btn = StyledButton(
            actions, text="Копировать",
            variant=VARIANT_PRIMARY, width=_ACTION_BUTTON_WIDTH,
            command=self._on_copy,
        )
        self._copy_btn.pack(side="left", padx=(0, _BUTTON_GAP))

        self._run_btn = StyledButton(
            actions, text="Запустить приложение",
            variant=VARIANT_SECONDARY, width=_ACTION_BUTTON_WIDTH,
            command=self._on_run,
        )
        self._run_btn.pack(side="left")

    # --- Разделитель ---

    def _build_separator(self) -> None:
        sep = tk.Frame(
            self,
            height=SEPARATOR_HEIGHT,
            bg=_separator_hex(),
            bd=0,
            highlightthickness=0,
        )
        sep.grid(
            row=2, column=0, sticky="ew",
            padx=24, pady=SEPARATOR_PADY,
        )
        sep.grid_propagate(False)

    # --- Нижний ряд кнопок ---

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
            self._name_label.configure(text="Профиль не найден")
            self._subtitle_label.configure(text="")
            for entry in (
                self._source_entry, self._dest_entry, self._exe_entry,
            ):
                self._set_readonly_text(entry, "")
            self._show_emoji_icon(DEFAULT_PROFILE_ICON)
            return

        self._name_label.configure(text=profile.display_name)
        self._subtitle_label.configure(
            text=self._subtitle_for(profile),
        )
        self._refresh_icon_label(profile)

        self._set_readonly_text(self._source_entry, profile.source)
        self._set_readonly_text(self._dest_entry, profile.destination)
        self._set_readonly_text(
            self._exe_entry,
            os.path.basename(profile.exe_relative)
            if profile.exe_relative else "",
        )

        self._backup_var.set(profile.create_backup)
        self._run_after_var.set(profile.run_after_copy)
        self._check_on_startup_var.set(profile.check_on_startup)

        self._update_buttons_state(profile)

    @staticmethod
    def _subtitle_for(profile: Profile) -> str:
        parts = []

        # Конфликт путей — приоритетнее всех прочих подсказок.
        conflict = _path_conflict_text(
            profile.source, profile.destination,
        )
        if conflict:
            return conflict

        if not profile.has_source_and_dest():
            parts.append("Директории не заданы")
        if not profile.exe_relative:
            parts.append("Приложение не выбрано")
        elif not profile.has_exe_in_source():
            parts.append("Файл приложения не найден в источнике")
        elif not profile.has_exe_in_destination():
            parts.append("Приложение ещё не скопировано")
        return "  ·  ".join(parts) if parts else "Профиль готов"

    @staticmethod
    def _set_readonly_text(entry: ctk.CTkEntry, value: str) -> None:
        entry.configure(state="normal")
        entry.delete(0, "end")
        if value:
            entry.insert(0, value)
        entry.configure(state="readonly")

    def _refresh_icon_label(self, profile: Profile) -> None:
        icon = profile.icon or DEFAULT_PROFILE_ICON

        if self._is_icon_file(icon):
            if self._try_show_image_icon(icon):
                return

        self._show_emoji_icon(icon)

    @staticmethod
    def _is_icon_file(icon: str) -> bool:
        if not icon:
            return False
        if "/" in icon or "\\" in icon:
            return True
        return icon.lower().endswith(
            (".png", ".ico", ".jpg", ".jpeg", ".gif", ".bmp")
        )

    def _try_show_image_icon(self, path: str) -> bool:
        try:
            from PIL import Image
            img = Image.open(path).convert("RGBA")
            max_side = _ICON_SIZE * _MAX_SCALING_HINT
            img.thumbnail((max_side, max_side), Image.LANCZOS)
            ctk_img = ctk.CTkImage(
                light_image=img, dark_image=img,
                size=(_ICON_SIZE, _ICON_SIZE),
            )
        except Exception as exc:
            logger.debug("Иконка профиля не загружена: %r", exc)
            return False

        self._icon_emoji_label.place_forget()
        self._icon_ctk = ctk_img
        self._icon_image_label.configure(image=ctk_img, text="")
        self._icon_image_label.place(
            relx=0.5, rely=0.5, anchor="center",
        )
        self._icon_image_label.lift()
        return True

    def _show_emoji_icon(self, text: str) -> None:
        self._icon_image_label.place_forget()
        self._icon_ctk = None
        self._icon_emoji_label.configure(text=text)
        self._icon_emoji_label.place(
            relx=0.5, rely=0.5, anchor="center",
        )
        self._icon_emoji_label.lift()

    def _update_buttons_state(self, profile: Profile) -> None:
        if self._busy:
            self._copy_btn.configure(state="disabled")
            self._run_btn.configure(state="disabled")
            return

        # Конфликт путей блокирует копирование независимо от того,
        # что ещё настроено в профиле.
        conflict = _path_conflict_text(
            profile.source, profile.destination,
        )
        if conflict:
            self._copy_btn.configure(state="disabled")
        else:
            self._copy_btn.configure(
                state="normal" if profile.has_source_and_dest()
                else "disabled",
            )

        self._run_btn.configure(
            state="normal" if profile.can_run() else "disabled",
        )

    # --- Source / destination / exe ---

    def _on_pick_source(self) -> None:
        profile = self._profile()
        if profile is None:
            return

        initial = (
            profile.source
            if profile.source and os.path.isdir(profile.source)
            else None
        )
        path = filedialog.askdirectory(
            parent=self.window,
            title="Выберите исходную директорию",
            initialdir=initial,
            mustexist=True,
        )
        if not path:
            return

        new_source = os.path.abspath(path)

        # Конфликт с уже выбранным destination — не принимаем.
        conflict = _path_conflict_text(
            new_source, profile.destination,
        )
        if conflict:
            show_error(
                self.window,
                "Неверная директория",
                (
                    f"{conflict}.\n\n"
                    f"Выберите другую папку-источник."
                ),
            )
            return

        profile.source = new_source
        profile.exe_relative = ""
        self._save_and_refresh()

    def _on_pick_destination(self) -> None:
        profile = self._profile()
        if profile is None:
            return

        initial = (
            profile.destination
            if profile.destination and os.path.isdir(profile.destination)
            else None
        )
        path = filedialog.askdirectory(
            parent=self.window,
            title="Выберите целевую директорию",
            initialdir=initial,
            mustexist=True,
        )
        if not path:
            return

        abs_path = os.path.abspath(path)

        # Прямой конфликт с source — не принимаем.
        conflict = _path_conflict_text(profile.source, abs_path)
        if conflict:
            show_error(
                self.window,
                "Неверная директория",
                (
                    f"{conflict}.\n\n"
                    f"Выберите другую папку назначения."
                ),
            )
            return

        resolved = self._resolve_destination_target(profile, abs_path)
        if resolved is None:
            return

        # Конфликт после создания вложенной папки: если source
        # лежит внутри родителя, а итог — src/source_name, то
        # итог окажется в source.
        conflict = _path_conflict_text(profile.source, resolved)
        if conflict:
            show_error(
                self.window,
                "Неверная директория",
                (
                    f"{conflict}.\n\n"
                    f"Выберите другую папку назначения."
                ),
            )
            return

        profile.destination = resolved
        self._save_and_refresh()

    def _resolve_destination_target(
        self, profile: Profile, abs_path: str,
    ) -> str | None:
        if not (profile.source and os.path.isdir(profile.source)):
            return abs_path

        source_name = os.path.basename(
            profile.source.rstrip("/\\"),
        )
        if not source_name:
            return abs_path

        last_segment = os.path.basename(abs_path.rstrip("/\\"))

        if last_segment.lower() == source_name.lower():
            return self._handle_existing_target(abs_path, source_name)

        target = os.path.join(abs_path, source_name)

        if os.path.isdir(target):
            return self._handle_existing_target(target, source_name)

        create = ask_yes_no(
            self.window,
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
            logger.error(
                "Не удалось создать %s: %r", target, exc,
            )
            show_error(
                self.window,
                "Не удалось создать папку",
                f"Путь: {target}\nОшибка: {exc}",
            )
            return None

        return target

    def _handle_existing_target(
        self, target: str, source_name: str,
    ) -> str | None:
        if _is_dir_empty(target):
            logger.debug(
                "Целевая папка %s существует, но пуста", target,
            )
            return target

        confirm = ask_yes_no(
            self.window,
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

    def _on_pick_exe(self) -> None:
        profile = self._profile()
        if profile is None:
            return

        if not (profile.source and os.path.isdir(profile.source)):
            show_error(
                self.window,
                "Не выбрана исходная директория",
                (
                    "Сначала укажите папку-источник — "
                    "приложение выбирается внутри неё."
                ),
            )
            return

        initial = profile.source
        path = filedialog.askopenfilename(
            parent=self.window,
            title="Выберите запускаемое приложение",
            initialdir=initial,
            filetypes=[("Программы", "*.exe"), ("Все файлы", "*.*")],
        )
        if not path:
            return

        abs_exe = os.path.abspath(path)
        rel = os.path.relpath(abs_exe, profile.source)

        if rel.startswith(".."):
            show_error(
                self.window,
                "Файл вне исходной директории",
                (
                    "Приложение должно находиться внутри папки "
                    "источника. Выберите .exe из "
                    f"{profile.source}."
                ),
            )
            return

        profile.exe_relative = rel
        self._maybe_set_icon_from_exe(profile)
        self._save_and_refresh()

    def _maybe_set_icon_from_exe(self, profile: Profile) -> None:
        if not profile.icon_auto:
            return

        full = profile.exe_source_path()
        if not full or not os.path.isfile(full):
            return

        png = save_exe_icon(Path(full), get_icons_dir())
        if png is None:
            logger.debug("Иконка exe не извлечена для %s", full)
            return

        profile.icon = str(png)

    # --- Чекбоксы ---

    def _on_backup_toggle(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        profile.create_backup = bool(self._backup_var.get())
        save_settings(self.window.settings)

    def _on_run_after_toggle(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        profile.run_after_copy = bool(self._run_after_var.get())
        save_settings(self.window.settings)

    def _on_check_on_startup_toggle(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        profile.check_on_startup = bool(
            self._check_on_startup_var.get(),
        )
        save_settings(self.window.settings)
        state = "включена" if profile.check_on_startup else "выключена"
        self.window.set_status(
            f"Автопроверка при запуске {state}",
        )

    # --- Иконка / имя / сброс / удаление ---

    def _on_change_icon(self) -> None:
        profile = self._profile()
        if profile is None:
            return

        full = profile.exe_source_path()
        exe_path = Path(full) if full and os.path.isfile(full) else None

        result = pick_icon(
            parent=self.window,
            current_icon=profile.icon,
            current_icon_auto=profile.icon_auto,
            exe_path=exe_path,
            parent_visible=True,
        )
        if result is None:
            return

        profile.icon, profile.icon_auto = result
        self._save_and_refresh()

    def _on_rename(self) -> None:
        profile = self._profile()
        if profile is None:
            return

        new_name = ask_profile_name(
            self.window, profile.display_name, True,
        )
        if new_name is None:
            return

        profile.name_manual = new_name
        profile.name_auto = False
        self._save_and_refresh()

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

    def _on_delete(self) -> None:
        profile = self._profile()
        if profile is None:
            return

        if not ask_delete_profile(
            self.window, profile.display_name, True,
        ):
            return

        removed = profile.display_name
        self.window.settings.profiles = [
            p for p in self.window.settings.profiles
            if p.id != profile.id
        ]
        save_settings(self.window.settings)

        self._profile_id = None
        self.window.refresh_sidebar()
        self.window.show_main()
        self.window.set_status(f"Профиль удалён: {removed}")

    # --- Копирование ---

    def _on_copy(self) -> None:
        profile = self._profile()
        if profile is None or self._busy:
            return

        # Страховка: даже если кнопка была разблокирована до
        # изменения путей, повторно проверяем конфликт.
        conflict = _path_conflict_text(
            profile.source, profile.destination,
        )
        if conflict:
            show_error(
                self.window,
                "Нельзя запустить копирование",
                (
                    f"{conflict}.\n\n"
                    f"Измените исходную или целевую директорию."
                ),
            )
            return

        self._set_busy(True)
        self.window.set_status_progress("Копирование…", 0.0)

        started = self.window.copy_service.start(
            source=profile.source,
            destination=profile.destination,
            create_backup=profile.create_backup,
            on_progress=self._on_copy_progress,
            on_done=lambda r, p=profile: self._on_copy_done(r, p),
            on_error=self._on_copy_error,
        )
        if not started:
            self._set_busy(False)

    def _on_copy_progress(self, progress) -> None:
        self.window.set_status_progress(
            f"Копирование: {progress.processed}/{progress.total}",
            progress.percent / 100.0,
        )

    def _on_copy_done(self, result: CopyResult, profile: Profile) -> None:
        self._set_busy(False)

        if result.cancelled:
            self.window.set_status_progress(
                "Копирование отменено", None,
            )
            return

        parts = [
            f"скопировано {result.copied}",
            f"пропущено {result.skipped}",
        ]
        if result.errors:
            parts.append(f"ошибок {result.errors}")
        text = "Копирование завершено: " + ", ".join(parts)
        self.window.set_status_progress(text, None)

        if result.backup_dir:
            self.window.set_status(
                f"{text}  ·  бэкап: {Path(result.backup_dir).name}",
            )

        profile.touch()
        save_settings(self.window.settings)

        self._reload_from_profile()

        if profile.run_after_copy and result.errors == 0:
            self._on_run()

    def _on_copy_error(self, message: str) -> None:
        self._set_busy(False)
        self.window.set_status_progress(
            f"Ошибка копирования: {message}", None,
        )
        show_error(
            self.window,
            "Ошибка копирования",
            message,
        )

    # --- Запуск ---

    def _on_run(self) -> None:
        profile = self._profile()
        if profile is None or self._busy:
            return

        full = profile.exe_full_path()
        try:
            launch_exe(full)
            profile.touch()
            save_settings(self.window.settings)
            self.window.set_status(
                f"Запущено: {Path(full).name}",
            )
        except LaunchError as exc:
            self.window.set_status(f"Ошибка запуска: {exc}")
            show_error(
                self.window,
                "Ошибка запуска",
                str(exc),
            )

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
