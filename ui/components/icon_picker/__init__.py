"""Пакет диалога выбора иконки профиля.

Публичный API:
    pick_icon(parent, current_icon, current_icon_auto, exe_path, parent_visible)

Возвращает (icon, icon_auto) или None при отмене.

Логика выбора — в IconPickerState (без tkinter, тестируется).
Диалог — в dialog.py (тонкий tkinter-слой).
"""

from .dialog import pick_icon
from .state import IconPickerState

__all__ = ["IconPickerState", "pick_icon"]
