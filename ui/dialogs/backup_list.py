"""Диалог списка состояний (резервных копий).

Модальный, изменяемого размера. Стартовый размер — 720×504.
Список прокручивается.

Детали показывают:
  • размер state;
  • «В проекте: N файлов, M папок» — состав состояния;
  • «Сохранены изменения: X файлов (Y)» — сколько новых
    уникальных blob-ов появилось при создании state.

Кнопка «Восстановить» — основная (синяя).
«Удалить» — неактивна для текущего состояния (защита).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime

import customtkinter as ctk

from services.cas.backup_registry import (
    StateUiInfo,
    compute_ui_info,
    delete_state,
    get_current,
    list_states,
)
from services.cas.state_store import StateInfo
from services.restore.disk_space import format_bytes
from ui.components.button import (
    VARIANT_DANGER,
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.components.scrollable import AutoHideScrollableFrame
from ui.components.separator import make_separator
from ui.dialogs import ask_yes_no, show_error
from ui.dialogs._centering import get_scaling as _get_scaling
from ui.dialogs._icon import apply_dialog_icon
from ui.fonts import get_font
from utils.logger import get_logger

logger = get_logger(__name__)

_DIALOG_WIDTH = 720
_DIALOG_HEIGHT = 504
_MIN_WIDTH = _DIALOG_WIDTH
_MIN_HEIGHT = _DIALOG_HEIGHT
_WRAP = 620

_ROW_PADY = 4
_TITLE_FONT_SIZE = 16
_ROW_FONT_SIZE = 13
_HINT_FONT_SIZE = 11

_ROW_BUTTON_WIDTH = 130
_ROW_BUTTON_HEIGHT = 28
_ROW_BUTTON_GAP = 6

_EMPTY_BG = ("gray88", "gray20")
_DETAILS_COLOR = ("gray40", "gray60")


def _format_date(info: StateInfo) -> str:
    if info.timestamp is not None:
        return info.timestamp.strftime("%d.%m.%Y %H:%M:%S")
    if info.created_at:
        try:
            dt = datetime.fromisoformat(info.created_at)
            return dt.strftime("%d.%m.%Y %H:%M:%S")
        except (ValueError, TypeError):
            pass
    return "—"


def _plural(
    n: int, one: str, few: str, many: str,
) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def _format_files(n: int) -> str:
    return f"{n} {_plural(n, 'файл', 'файла', 'файлов')}"


def _format_dirs(n: int) -> str:
    return f"{n} {_plural(n, 'папка', 'папки', 'папок')}"


def _build_title(ui: StateUiInfo) -> str:
    parts = [_format_date(ui.info)]
    if ui.is_current:
        parts.append("Текущий")
    if ui.is_restore_point:
        parts.append("Точка возврата")
    return "  ·  ".join(parts)


def _build_details(ui: StateUiInfo) -> str:
    info = ui.info
    parts: list[str] = [
        "В проекте: "
        f"{_format_files(info.files_count)}, "
        f"{_format_dirs(info.empty_dirs_count)} "
        f"({format_bytes(info.total_size)})"
    ]
    if info.new_blobs_count > 0:
        parts.append(
            "Сохранены изменения: "
            f"{_format_files(info.new_blobs_count)} "
            f"({format_bytes(info.new_blobs_bytes)})"
        )
    else:
        parts.append("Изменений нет")
    return "  ·  ".join(parts)


class _StateRow(ctk.CTkFrame):
    def __init__(
        self,
        master,
        ui: StateUiInfo,
        *,
        can_delete: bool,
        on_delete,
        on_restore,
    ):
        super().__init__(
            master,
            fg_color=_EMPTY_BG,
            corner_radius=6,
        )
        self.grid_columnconfigure(0, weight=1)

        self._ui = ui
        self._on_delete = on_delete
        self._on_restore = on_restore

        text_box = ctk.CTkFrame(self, fg_color="transparent")
        text_box.grid(
            row=0, column=0, sticky="ew",
            padx=(12, 12), pady=(8, 4),
        )
        text_box.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            text_box,
            text=_build_title(ui),
            anchor="w",
            justify="left",
            font=get_font(_ROW_FONT_SIZE, "bold"),
            wraplength=_WRAP,
        ).grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(
            text_box,
            text=_build_details(ui),
            anchor="w",
            justify="left",
            font=get_font(_HINT_FONT_SIZE),
            text_color=_DETAILS_COLOR,
            wraplength=_WRAP,
        ).grid(row=1, column=0, sticky="ew")

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(
            row=1, column=0, sticky="e",
            padx=(12, 12), pady=(0, 8),
        )

        restore_btn = StyledButton(
            btns,
            text="Восстановить",
            variant=VARIANT_PRIMARY,
            width=_ROW_BUTTON_WIDTH,
            height=_ROW_BUTTON_HEIGHT,
            command=lambda: self._on_restore(self._ui),
        )
        if ui.is_current:
            restore_btn.configure(state="disabled")
        restore_btn.pack(
            side="left", padx=(0, _ROW_BUTTON_GAP),
        )

        delete_btn = StyledButton(
            btns,
            text="Удалить",
            variant=VARIANT_DANGER,
            width=_ROW_BUTTON_WIDTH,
            height=_ROW_BUTTON_HEIGHT,
            command=lambda: self._on_delete(self._ui),
        )
        if not can_delete:
            delete_btn.configure(state="disabled")
        delete_btn.pack(side="left")


class _BackupListDialog:
    def __init__(
        self,
        parent,
        profile_name: str,
        destination: str,
        parent_visible: bool,
        on_restore: Callable[[str], None] | None,
    ):
        self._parent = parent
        self._profile_name = profile_name
        self._destination = destination
        self._parent_visible = parent_visible
        self._on_restore = on_restore
        self._pending_restore: str | None = None

        logger.info(
            "Открытие диалога «Резервные копии»: профиль=%r, "
            "destination=%r",
            profile_name, destination,
        )

        self._dialog = ctk.CTkToplevel(parent)
        self._dialog.title("Резервные копии")
        self._dialog.resizable(True, True)
        self._dialog.minsize(_MIN_WIDTH, _MIN_HEIGHT)
        self._dialog.grid_columnconfigure(0, weight=1)
        self._dialog.grid_rowconfigure(2, weight=1)

        try:
            apply_dialog_icon(self._dialog)
        except Exception as exc:
            logger.debug("apply_dialog_icon: %r", exc)

        if parent_visible:
            try:
                self._dialog.transient(
                    parent.winfo_toplevel(),
                )
            except Exception as exc:
                logger.debug("transient: %r", exc)

        self._dialog.protocol(
            "WM_DELETE_WINDOW", self._dialog.destroy,
        )

        self._build()

        try:
            self._reload()
        except Exception as exc:
            logger.exception(
                "Ошибка построения списка состояний: %r", exc,
            )
            try:
                self._show_message(
                    f"Не удалось загрузить список состояний:\n"
                    f"{type(exc).__name__}: {exc}"
                )
            except Exception as inner_exc:
                logger.exception(
                    "Не удалось показать сообщение об ошибке: %r",
                    inner_exc,
                )

    def run(self) -> None:
        try:
            self._dialog.update_idletasks()
            self._dialog.deiconify()
            self._dialog.lift()
            self._dialog.focus_force()
        except Exception as exc:
            logger.error("Показ диалога упал: %r", exc)

        self._position_and_size()

        try:
            self._dialog.wait_visibility()
        except Exception as exc:
            logger.error("wait_visibility упал: %r", exc)

        try:
            self._dialog.grab_set()
        except Exception as exc:
            logger.error("grab_set упал: %r", exc)

        try:
            self._parent.wait_window(self._dialog)
        except Exception as exc:
            logger.debug("wait_window: %r", exc)

        if (
            self._pending_restore
            and self._on_restore is not None
        ):
            ref = self._pending_restore
            self._pending_restore = None
            try:
                self._on_restore(ref)
            except Exception as exc:
                logger.exception(
                    "callback on_restore упал: %r", exc,
                )

    def _position_and_size(self) -> None:
        """Центрирует диалог по родителю в ФИЗИЧЕСКИХ пикселях.

        winfo_* возвращают физические пиксели, поэтому размер диалога
        тоже масштабируется, а применяется через wm_geometry: CTk-
        обёртка geometry() умножила бы и позицию — окно уехало бы
        при DPI > 100%.
        """
        scaling = _get_scaling(self._dialog)

        try:
            px = self._parent.winfo_rootx()
            py = self._parent.winfo_rooty()
            pw = self._parent.winfo_width()
            ph = self._parent.winfo_height()
        except Exception as exc:
            logger.debug("геометрия родителя: %r", exc)
            px = py = 100
            pw = ph = 1200

        dw = int(round(_DIALOG_WIDTH * scaling))
        dh = int(round(_DIALOG_HEIGHT * scaling))

        x = px + max(0, (pw - dw) // 2)
        y = py + max(0, (ph - dh) // 2)

        try:
            self._dialog.wm_geometry(f"{dw}x{dh}+{x}+{y}")
        except Exception as exc:
            logger.error("wm_geometry диалога: %r", exc)

    def _build(self) -> None:
        header = ctk.CTkFrame(
            self._dialog, fg_color="transparent",
        )
        header.grid(
            row=0, column=0, sticky="ew",
            padx=20, pady=(20, 8),
        )
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Резервные копии",
            anchor="w",
            font=get_font(_TITLE_FONT_SIZE, "bold"),
        ).grid(row=0, column=0, sticky="w")

        if self._profile_name:
            ctk.CTkLabel(
                header,
                text=self._profile_name,
                anchor="w",
                font=get_font(_HINT_FONT_SIZE),
                text_color=("gray40", "gray60"),
            ).grid(row=1, column=0, sticky="w")

        sep = make_separator(self._dialog)
        sep.grid(
            row=1, column=0, sticky="ew",
            padx=20, pady=(0, 8),
        )

        self._list_frame = AutoHideScrollableFrame(
            self._dialog,
            fg_color="transparent",
            corner_radius=0,
        )
        self._list_frame.grid(
            row=2, column=0, sticky="nsew",
            padx=20, pady=(0, 8),
        )
        self._list_frame.grid_columnconfigure(0, weight=1)

        bottom = ctk.CTkFrame(
            self._dialog, fg_color="transparent",
        )
        bottom.grid(
            row=3, column=0, sticky="ew",
            padx=20, pady=(0, 20),
        )
        bottom.grid_columnconfigure(0, weight=1)

        StyledButton(
            bottom,
            text="Закрыть",
            variant=VARIANT_SECONDARY,
            width=140,
            height=32,
            command=self._dialog.destroy,
        ).grid(row=0, column=1, sticky="e")

    def _reload(self) -> None:
        for child in self._list_frame.winfo_children():
            child.destroy()

        if not self._destination:
            self._show_message(
                "Целевая директория не задана.\n\n"
                "Укажите папку назначения в профиле, чтобы "
                "увидеть резервные копии."
            )
            return

        if not os.path.isdir(self._destination):
            self._show_message(
                "Папка назначения не существует:\n"
                f"{self._destination}\n\n"
                "Возможно, она была удалена или перемещена."
            )
            return

        states = list_states(self._destination)
        if not states:
            self._show_message(
                "Резервных копий пока нет.\n\n"
                "Состояние создаётся автоматически при "
                "копировании с изменениями."
            )
            return

        current = get_current(self._destination)

        for idx, info in enumerate(states):
            ui = compute_ui_info(info, current)
            row = _StateRow(
                self._list_frame,
                ui,
                can_delete=not ui.is_current,
                on_delete=self._handle_delete,
                on_restore=self._handle_restore,
            )
            row.grid(
                row=idx, column=0, sticky="ew",
                padx=4, pady=(0, _ROW_PADY),
            )

        try:
            self._list_frame.check_scroll()
        except Exception as exc:
            logger.debug("check_scroll: %r", exc)

    def _show_message(self, text: str) -> None:
        ctk.CTkLabel(
            self._list_frame,
            text=text,
            anchor="w",
            justify="left",
            wraplength=_WRAP,
            font=get_font(_ROW_FONT_SIZE),
            text_color=("gray40", "gray60"),
        ).grid(
            row=0, column=0, sticky="w",
            padx=12, pady=16,
        )

    def _handle_delete(self, ui: StateUiInfo) -> None:
        if ui.is_current:
            return

        confirm = ask_yes_no(
            self._dialog,
            "Удалить состояние",
            (
                f"Удалить резервную копию?\n\n"
                f"Дата: {_format_date(ui.info)}\n"
                f"Имя: {ui.name}\n\n"
                f"Действие нельзя отменить. Связанные с этим "
                f"состоянием файлы будут удалены из хранилища, "
                f"если на них не ссылаются другие состояния."
            ),
            yes_text="Удалить",
            no_text="Отмена",
            parent_visible=self._parent_visible,
        )
        if not confirm:
            return

        ok, err = delete_state(
            self._destination, ui.info.path,
        )
        if not ok:
            show_error(
                self._dialog,
                "Не удалось удалить состояние",
                f"Имя: {ui.name}\nОшибка: {err}",
                parent_visible=self._parent_visible,
            )
            return

        self._reload()

    def _handle_restore(self, ui: StateUiInfo) -> None:
        if ui.is_current:
            return
        if self._on_restore is None:
            return

        confirm = ask_yes_no(
            self._dialog,
            "Восстановить из резервной копии",
            (
                f"Восстановить версию от "
                f"{_format_date(ui.info)}?\n\n"
                f"Файлы, изменённые после этой версии, будут "
                f"перезаписаны.\n\n"
                f"Текущее состояние будет сохранено как "
                f"«Точка возврата» — если результат не "
                f"подойдёт, можно будет откатиться."
            ),
            yes_text="Восстановить",
            no_text="Отмена",
            parent_visible=self._parent_visible,
        )
        if not confirm:
            return

        self._pending_restore = ui.name
        self._dialog.destroy()


def open_backup_list(
    parent,
    profile_name: str,
    destination: str,
    parent_visible: bool,
    on_restore: Callable[[str], None] | None = None,
) -> None:
    """Открывает модальный диалог списка состояний."""
    try:
        _BackupListDialog(
            parent,
            profile_name=profile_name,
            destination=destination,
            parent_visible=parent_visible,
            on_restore=on_restore,
        ).run()
    except Exception as exc:
        logger.exception(
            "Не удалось открыть диалог «Резервные копии»: %r",
            exc,
        )
        show_error(
            parent,
            "Ошибка открытия диалога",
            f"{type(exc).__name__}: {exc}",
            parent_visible=parent_visible,
        )
