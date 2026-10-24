"""Диалог «Недостаточно места на диске»."""

from __future__ import annotations

import customtkinter as ctk

from services.restore.disk_space import DiskSpaceCheck, format_bytes
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


def _build_details(check: DiskSpaceCheck) -> str:
    """Текст с разбивкой по категориям (что и сколько займёт)."""
    lines: list[str] = []

    if check.new_files_count:
        lines.append(
            f"Новые файлы: {format_bytes(check.new_files_bytes)} "
            f"({check.new_files_count} шт.)"
        )
    if check.replaced_files_count:
        lines.append(
            f"Замены: {format_bytes(check.replaced_files_bytes)} "
            f"({check.replaced_files_count} шт.)"
        )
    if check.backup_files_count:
        lines.append(
            f"Резервные копии замен: "
            f"{format_bytes(check.backup_files_bytes)} "
            f"({check.backup_files_count} шт.)"
        )

    if not lines:
        return ""

    return "\n".join(lines)


def confirm_insufficient_space(
    parent,
    check: DiskSpaceCheck,
    parent_visible: bool,
) -> bool:
    """Спрашивает, продолжать ли копирование.

    Возвращает True — продолжать. False — отменить.
    """
    result = {"value": False}

    dialog = setup_dialog(
        parent, "Недостаточно места", parent_visible,
    )

    ctk.CTkLabel(
        dialog,
        text="Недостаточно места на диске",
        anchor="center",
        font=get_font(15, "bold"),
    ).pack(padx=32, pady=(24, 8), fill="x")

    summary = (
        f"Требуется: {format_bytes(check.needed_bytes)}\n"
        f"Доступно: {format_bytes(check.available_bytes)}"
    )
    ctk.CTkLabel(
        dialog,
        text=summary,
        anchor="center",
        justify="center",
        font=get_font(13),
    ).pack(padx=32, pady=(0, 12), fill="x")

    details = _build_details(check)
    if details:
        ctk.CTkLabel(
            dialog,
            text=details,
            anchor="center",
            justify="center",
            wraplength=_WRAP,
            text_color=("gray40", "gray60"),
            font=get_font(11),
        ).pack(padx=32, pady=(0, 12), fill="x")

    ctk.CTkLabel(
        dialog,
        text=(
            "Копирование может завершиться с ошибкой, если места "
            "не хватит. Продолжить?"
        ),
        anchor="center",
        justify="center",
        wraplength=_WRAP,
        text_color=("gray40", "gray60"),
        font=get_font(11),
    ).pack(padx=32, pady=(0, 16), fill="x")

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
