"""Диалог подтверждения режима зеркала.

Показывается, если pre-scan показывает, что mirror уберёт больше
половины файлов из папки назначения. Это часто признак ошибки
выбора source или существенного расхождения версий — просим
пользователя проверить папку назначения, прежде чем продолжать.

В шапке диалога — контекст:
  • «Автопроверка при запуске» (если диалог из автопроверки);
  • название профиля.
"""

from __future__ import annotations

import customtkinter as ctk

from services.copy.mirror_check import MirrorStats
from ui.components.button import (
    VARIANT_DANGER,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.dialogs._centering import (
    bring_to_front,
    center_on_parent,
)
from ui.dialogs._setup import setup_dialog
from ui.fonts import get_font

_WRAP = 480
_BUTTON_WIDTH = 140


def confirm_mirror(
    parent,
    stats: MirrorStats,
    parent_visible: bool,
    *,
    profile_name: str = "",
    is_startup_check: bool = False,
) -> bool:
    """Спрашивает, продолжать ли копирование с mirror.

    profile_name — название профиля. Показывается над заголовком.
    is_startup_check — True, если диалог вызван автопроверкой.
    Возвращает True — продолжать. False — отменить.
    """
    result = {"value": False}

    dialog = setup_dialog(
        parent, "Режим зеркала", parent_visible,
    )

    # --- Контекст в шапке ---
    header_shown = False

    if is_startup_check:
        ctk.CTkLabel(
            dialog,
            text="Автопроверка при запуске",
            anchor="center",
            text_color=("gray40", "gray60"),
            font=get_font(11),
        ).pack(padx=32, pady=(20, 2), fill="x")
        header_shown = True

    if profile_name:
        top = 2 if header_shown else 20
        ctk.CTkLabel(
            dialog,
            text=profile_name,
            anchor="center",
            font=get_font(13, "bold"),
        ).pack(padx=32, pady=(top, 8), fill="x")
        header_shown = True

    # --- Основной заголовок (call to action) ---
    title_top = 8 if header_shown else 24
    ctk.CTkLabel(
        dialog,
        text="Проверьте папку назначения",
        anchor="center",
        font=get_font(15, "bold"),
    ).pack(padx=32, pady=(title_top, 8), fill="x")

    # --- Цифры ---
    ratio_pct = int(round(stats.files_ratio * 100))
    summary = (
        f"Больше половины содержимого папки назначения "
        f"отсутствует в источнике: "
        f"{len(stats.files_to_remove)} из "
        f"{stats.total_destination_files} файлов ({ratio_pct}%)"
    )
    if stats.dirs_to_remove:
        summary += f" и {len(stats.dirs_to_remove)} папок"

    ctk.CTkLabel(
        dialog,
        text=summary,
        anchor="center",
        justify="center",
        wraplength=_WRAP,
        font=get_font(13),
    ).pack(padx=32, pady=(0, 12), fill="x")

    # --- Объяснение, почему важно проверить ---
    ctk.CTkLabel(
        dialog,
        text=(
            "Возможно, выбрана не та папка-источник, или версии "
            "существенно отличаются друг от друга. Убедитесь, что "
            "копирование идёт из нужного места."
        ),
        anchor="center",
        justify="center",
        wraplength=_WRAP,
        text_color=("gray40", "gray60"),
        font=get_font(11),
    ).pack(padx=32, pady=(0, 8), fill="x")

    # --- Успокаивающий текст про бэкап ---
    ctk.CTkLabel(
        dialog,
        text=(
            "Все убранные файлы и папки будут перемещены в "
            "папку резервных копий — их можно будет восстановить."
        ),
        anchor="center",
        justify="center",
        wraplength=_WRAP,
        text_color=("gray40", "gray60"),
        font=get_font(11),
    ).pack(padx=32, pady=(0, 16), fill="x")

    # --- Кнопки ---
    btns = ctk.CTkFrame(dialog, fg_color="transparent")
    btns.pack(pady=(0, 20))

    def on_continue() -> None:
        result["value"] = True
        dialog.destroy()

    def on_cancel() -> None:
        result["value"] = False
        dialog.destroy()

    StyledButton(
        btns,
        text="Продолжить",
        variant=VARIANT_DANGER,
        width=_BUTTON_WIDTH,
        command=on_continue,
    ).pack(side="left", padx=(0, 8))

    StyledButton(
        btns,
        text="Отмена",
        variant=VARIANT_SECONDARY,
        width=_BUTTON_WIDTH,
        command=on_cancel,
    ).pack(side="left")

    dialog.bind("<Escape>", lambda _e: on_cancel())
    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    center_on_parent(dialog, parent)
    bring_to_front(dialog, parent_visible)
    parent.wait_window(dialog)

    return result["value"]
