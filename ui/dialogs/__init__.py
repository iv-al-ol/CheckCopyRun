"""Универсальные диалоги, стилизованные под CustomTkinter.

Публичный API (для импорта `from ui.dialogs import ...`):

  setup_dialog(parent, title, parent_visible) -> CTkToplevel
  center_on_parent(dialog, parent)
  bring_to_front(dialog, parent_visible)

  show_info, show_warning, show_error — однокнопочные
  ask_yes_no                          — да/нет

Модули пакета:
  _icon      — иконка диалога + кэш PhotoImage
  _centering — центрирование, WinAPI, мониторы
  _setup     — фабрика setup_dialog
  _standard  — стандартные info/warning/error/yes-no

Специализированные диалоги (profile_dialogs, notifications и т.п.)
живут отдельными модулями и используют этот API.
"""

from __future__ import annotations

from ui.dialogs._centering import (
    bring_to_front,
    center_on_parent,
)
from ui.dialogs._setup import setup_dialog
from ui.dialogs._standard import (
    ask_yes_no,
    show_error,
    show_info,
    show_warning,
)

__all__ = [
    "ask_yes_no",
    "bring_to_front",
    "center_on_parent",
    "setup_dialog",
    "show_error",
    "show_info",
    "show_warning",
]
