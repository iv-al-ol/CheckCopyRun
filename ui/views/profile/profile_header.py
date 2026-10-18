"""Шапка профиля: иконка, имя, подпись."""

from __future__ import annotations

import customtkinter as ctk

from config.constants import DEFAULT_PROFILE_ICON
from core.models import Profile
from ui.components.image_utils import (
    load_ctk_image,
    looks_like_image_path,
)
from ui.fonts import get_emoji_font, get_font
from utils.logger import get_logger

logger = get_logger(__name__)

_ICON_SIZE = 40
_ICON_CONTAINER_SIZE = _ICON_SIZE + 8
_TITLE_FONT_SIZE = 20


class ProfileHeader(ctk.CTkFrame):
    """Шапка: иконка + имя + подпись."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)

        icon_frame = ctk.CTkFrame(
            self,
            fg_color="transparent",
            width=_ICON_CONTAINER_SIZE,
            height=_ICON_CONTAINER_SIZE,
        )
        icon_frame.grid(
            row=0, column=0, rowspan=2, padx=(0, 12),
        )
        icon_frame.grid_propagate(False)

        self._icon_emoji_label = ctk.CTkLabel(
            icon_frame,
            text=DEFAULT_PROFILE_ICON,
            anchor="center",
            font=get_emoji_font(24),
        )
        self._icon_emoji_label.place(
            relx=0.5, rely=0.5, anchor="center",
        )

        self._icon_image_label = ctk.CTkLabel(
            icon_frame, text="", anchor="center",
        )
        self._icon_ctk = None

        self._name_label = ctk.CTkLabel(
            self,
            text="Профиль",
            anchor="w",
            font=get_font(_TITLE_FONT_SIZE, "bold"),
        )
        self._name_label.grid(row=0, column=1, sticky="w")

        self._subtitle_label = ctk.CTkLabel(
            self,
            text="",
            anchor="w",
            text_color=("gray40", "gray60"),
            font=get_font(11),
        )
        self._subtitle_label.grid(row=1, column=1, sticky="w")

    def update(self, profile: Profile, subtitle: str) -> None:
        self._name_label.configure(text=profile.display_name)
        self._subtitle_label.configure(text=subtitle)
        self._refresh_icon(profile.icon or DEFAULT_PROFILE_ICON)

    def clear(self) -> None:
        self._name_label.configure(text="Профиль не найден")
        self._subtitle_label.configure(text="")
        self._show_emoji(DEFAULT_PROFILE_ICON)

    def _refresh_icon(self, icon: str) -> None:
        if looks_like_image_path(icon) and self._try_show_image(icon):
            return
        self._show_emoji(icon)

    def _try_show_image(self, path: str) -> bool:
        ctk_img = load_ctk_image(path, _ICON_SIZE)
        if ctk_img is None:
            return False

        self._icon_emoji_label.place_forget()
        self._icon_ctk = ctk_img
        self._icon_image_label.configure(image=ctk_img, text="")
        self._icon_image_label.place(
            relx=0.5, rely=0.5, anchor="center",
        )
        self._icon_image_label.lift()
        return True

    def _show_emoji(self, text: str) -> None:
        self._icon_image_label.place_forget()
        self._icon_ctk = None
        self._icon_emoji_label.configure(text=text)
        self._icon_emoji_label.place(
            relx=0.5, rely=0.5, anchor="center",
        )
        self._icon_emoji_label.lift()
