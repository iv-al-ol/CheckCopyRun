"""Общая фабрика диалоговых окон.

Создаёт CTkToplevel с заголовком, иконкой, grab_set и (опционально)
transient-связью с родителем. Все диалоги проекта используют
эту функцию — единый стандарт поведения.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.dialogs._icon import apply_dialog_icon
from utils.logger import get_logger

logger = get_logger(__name__)


def setup_dialog(
    parent,
    title: str,
    parent_visible: bool = True,
) -> ctk.CTkToplevel:
    """Создаёт диалог с иконкой и grab_set.

    parent_visible — сделать transient (привязка к родителю).
    Для свёрнутого родителя transient не ставим — иначе Windows
    может показать диалог в неожиданном месте.
    """
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    apply_dialog_icon(dialog)

    if parent_visible:
        try:
            dialog.transient(parent.winfo_toplevel())
        except Exception as exc:
            logger.debug("transient() не удался: %r", exc)

    try:
        dialog.grab_set()
    except Exception as exc:
        logger.debug("grab_set не удался: %r", exc)

    return dialog
