"""Иконка для навигационных пунктов: эмодзи или картинка из файла.

Внутри — контейнер фиксированного размера с двумя независимыми
label: эмодзи и картинка. Виден всегда ровно один. При загрузке
картинки используется image_utils.load_ctk_image с логическим
размером — корректно масштабируется под DPI.

Если передан путь к файлу, но загрузить его не удалось — fallback
на дефолтную эмодзи (DEFAULT_PROFILE_ICON). Если передан путь и
картинка загрузилась — показывается картинка.

Если передан не путь (эмодзи) — показывается эмодзи как текст.

Использование:
    icon = NavIcon(parent, size=28)
    icon.grid(row=0, column=0, padx=(8, 4))
    icon.set_icon("🏠")
    icon.set_icon(r"C:\\path\\to\\icon.png")
    for w in icon.get_bindable_widgets():
        w.bind("<Button-1>", handler, add="+")
"""

from __future__ import annotations

import customtkinter as ctk

from config.constants import DEFAULT_PROFILE_ICON
from ui.components.image_utils import (
    load_ctk_image,
    looks_like_image_path,
)
from ui.fonts import get_emoji_font
from utils.logger import get_logger

logger = get_logger(__name__)

_EMOJI_FONT_SIZE = 14
_DEFAULT_SIZE = 28


class NavIcon(ctk.CTkFrame):
    """Иконка пункта навигации: эмодзи или картинка."""

    def __init__(
        self,
        master,
        *,
        size: int = _DEFAULT_SIZE,
        emoji_font_size: int = _EMOJI_FONT_SIZE,
        text_color=None,
    ):
        super().__init__(
            master,
            fg_color="transparent",
            width=size,
            height=size,
        )
        self.grid_propagate(False)
        self.pack_propagate(False)

        self._size = size
        self._emoji_font_size = emoji_font_size
        self._text_color = text_color

        self._emoji_label = ctk.CTkLabel(
            self,
            text=DEFAULT_PROFILE_ICON,
            anchor="center",
            font=get_emoji_font(emoji_font_size),
            text_color=text_color,
        )
        self._emoji_label.place(
            relx=0.5, rely=0.5, anchor="center",
        )

        self._image_label = ctk.CTkLabel(
            self, text="", anchor="center",
        )
        self._image_ctk = None

    # --- Публичное ---

    def set_icon(self, icon: str) -> None:
        """Устанавливает иконку: эмодзи или путь к файлу."""
        if looks_like_image_path(icon):
            img = load_ctk_image(icon, self._size)
            if img is not None:
                self._show_image(img)
                return
            # Файл не загрузился — fallback на дефолтную эмодзи.
            self._show_emoji(DEFAULT_PROFILE_ICON)
            return

        text = icon or DEFAULT_PROFILE_ICON
        self._show_emoji(text)

    def get_bindable_widgets(self) -> list:
        """Виджеты, на которые надо навешивать обработчики кликов.

        Включает сам контейнер и оба label — потому что клик по
        внутреннему CTkLabel не всегда поднимается до CTkFrame
        из-за особенностей bindtags.
        """
        return [self, self._emoji_label, self._image_label]

    # --- Внутреннее ---

    def _show_emoji(self, text: str) -> None:
        self._image_label.place_forget()
        self._image_ctk = None

        self._emoji_label.configure(
            text=text,
            font=get_emoji_font(self._emoji_font_size),
            text_color=self._text_color,
        )
        self._emoji_label.place(
            relx=0.5, rely=0.5, anchor="center",
        )
        self._emoji_label.lift()

    def _show_image(self, img) -> None:
        self._emoji_label.place_forget()

        self._image_ctk = img
        self._image_label.configure(image=img, text="")
        self._image_label.place(
            relx=0.5, rely=0.5, anchor="center",
        )
        self._image_label.lift()
