"""Управление темой приложения."""


import customtkinter as ctk

THEME_TO_MODE = {
    "system": "System",
    "dark": "Dark",
    "light": "Light",
}

THEME_LABELS = {
    "system": "Системная",
    "dark": "Тёмная",
    "light": "Светлая",
}


def apply_theme(name: str) -> None:
    mode = THEME_TO_MODE.get(name, "System")
    ctk.set_appearance_mode(mode)
