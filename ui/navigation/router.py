"""Менеджер экранов: ленивое создание и переключение.

Views создаются при первом show или get_or_create через фабрику,
затем кэшируются. Активным в grid'е держится только один view —
остальные убраны через grid_forget.
"""

from collections.abc import Callable

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger(__name__)

ViewFactory = Callable[[], ctk.CTkFrame]


class Router:
    def __init__(self, container: ctk.CTkFrame):
        self._container = container
        self._container.grid_rowconfigure(0, weight=1)
        self._container.grid_columnconfigure(0, weight=1)

        self._factories: dict[str, ViewFactory] = {}
        self._views: dict[str, ctk.CTkFrame] = {}
        self._current: str | None = None
        self._current_view: ctk.CTkFrame | None = None
        self._on_change: Callable[[str], None] | None = None

    @property
    def current(self) -> str | None:
        return self._current

    def register(self, key: str, factory: ViewFactory) -> None:
        """Регистрирует фабрику view. Сам view не создаётся."""
        if key in self._factories:
            logger.warning(
                "view с ключом %r уже зарегистрирован", key,
            )
            return
        self._factories[key] = factory

    def register_view(self, key: str, view: ctk.CTkFrame) -> None:
        """Регистрирует уже созданный view (для динамических экранов)."""
        if key in self._views:
            logger.warning(
                "view с ключом %r уже зарегистрирован", key,
            )
            return
        self._views[key] = view

    def get_view(self, key: str) -> ctk.CTkFrame | None:
        """Возвращает созданный view или None."""
        return self._views.get(key)

    def get_or_create(self, key: str) -> ctk.CTkFrame | None:
        """Возвращает view, создавая его при необходимости.

        Нужен тем, кто хочет настроить view до его показа
        (например, set_profile).
        """
        existing = self._views.get(key)
        if existing is not None:
            return existing
        return self._create_view(key)

    def on_change(self, callback: Callable[[str], None]) -> None:
        self._on_change = callback

    def show(self, key: str) -> None:
        if key not in self._factories and key not in self._views:
            logger.warning(
                "попытка показать незарегистрированный экран: %r", key,
            )
            return

        view = self._views.get(key)
        if view is None:
            view = self._create_view(key)
            if view is None:
                return

        if self._current_view is view:
            self._notify_change(key)
            self._call_on_show(view, key)
            return

        if self._current_view is not None:
            try:
                self._current_view.grid_forget()
            except Exception as exc:
                logger.debug(
                    "grid_forget предыдущего view не удался: %r", exc,
                )

        view.grid(row=0, column=0, sticky="nsew")
        self._current_view = view
        self._current = key

        self._notify_change(key)
        self._call_on_show(view, key)

    # --- Внутреннее ---

    def _create_view(self, key: str) -> ctk.CTkFrame | None:
        factory = self._factories.get(key)
        if factory is None:
            logger.warning("нет фабрики для view с ключом %r", key)
            return None

        try:
            view = factory()
        except Exception as exc:
            logger.exception(
                "не удалось создать view %r: %r", key, exc,
            )
            return None

        self._views[key] = view
        logger.debug("view %r создан по требованию", key)
        return view

    def _notify_change(self, key: str) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(key)
        except Exception as exc:
            logger.error("ошибка on_change для %r: %r", key, exc)

    @staticmethod
    def _call_on_show(view: ctk.CTkFrame, key: str) -> None:
        on_show = getattr(view, "on_show", None)
        if not callable(on_show):
            return
        try:
            on_show()
        except Exception as exc:
            logger.error("ошибка on_show экрана %r: %r", key, exc)
