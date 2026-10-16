"""Базовый класс для всех экранов."""


import customtkinter as ctk


class BaseView(ctk.CTkFrame):
    def __init__(self, master, window, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.window = window

    def on_show(self) -> None:
        """Вызывается при каждом показе экрана. Переопределяется."""
