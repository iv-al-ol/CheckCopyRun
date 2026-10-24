"""Базовый класс для вкладок настроек."""

from __future__ import annotations

import customtkinter as ctk

from core.settings_store import save_settings


class SettingsTab(ctk.CTkFrame):
    """Вкладка внутри SettingsView.

    Хранит ссылку на главное окно (window) для доступа к settings
    и общим коллбэкам (set_status, save_settings_now).
    """

    def __init__(self, master, window, **kwargs):
        super().__init__(
            master, fg_color="transparent", **kwargs,
        )
        self.window = window
        self.grid_columnconfigure(0, weight=1)

    def on_show(self) -> None:
        """Вызывается при показе вкладки. Переопределяется."""

    def save_and_notify(self, status: str) -> None:
        """Сохраняет настройки и выставляет статус."""
        try:
            save_settings(self.window.settings)
        except Exception:
            # Ошибку сохранения обработает window.save_settings_now.
            pass
        self.window.set_status(status)
