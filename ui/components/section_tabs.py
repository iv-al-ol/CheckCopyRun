"""Горизонтальные вкладки для разбиения раздела на подразделы.

Содержимое вкладки создаётся лениво: add_tab принимает фабрику
(Callable[[], CTkFrame]), а view конструируется при первом show.
До этого вкладка представлена только кнопкой.

Переукладка кнопок через grid_configure (без grid_forget) —
быстро и без каскада <Configure> на родителях.
"""

import time
from collections.abc import Callable

import customtkinter as ctk

from ui.fonts import get_font
from ui.palette import (
    SURFACE_ACTIVE,
    SURFACE_BG,
    SURFACE_HOVER,
    SURFACE_RADIUS,
    SURFACE_TEXT,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_TAB_HEIGHT = 34
_TAB_PADX_RIGHT = 4
_TAB_PADY_BOTTOM = 4
_FONT_SIZE = 13
_REFLOW_DELAY_MS = 60
_MIN_WIDTH_DELTA = 8
_DEBUG_SLOW_MS = 15

TabFactory = Callable[[], ctk.CTkFrame]


class SectionTabs(ctk.CTkFrame):
    """Вкладки-подразделы с ленивым созданием содержимого."""

    def __init__(
        self,
        master,
        on_change: Callable[[str], None] | None = None,
    ):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._on_change = on_change
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._factories: dict[str, TabFactory] = {}
        self._views: dict[str, ctk.CTkFrame] = {}
        self._current: str | None = None
        self._current_view: ctk.CTkFrame | None = None

        self._reflow_job: str | None = None
        self._last_bar_width = 0
        self._last_applied_width = 0
        self._last_layout: list[list[str]] = []
        self._in_reflow = False

        self._tab_bar = ctk.CTkFrame(self, fg_color="transparent")
        self._tab_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._tab_bar.bind("<Configure>", self._on_tab_bar_configure)

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.grid(row=1, column=0, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

    @property
    def current(self) -> str | None:
        return self._current

    def add_tab(
        self,
        key: str,
        label: str,
        factory: TabFactory,
    ) -> None:
        """Регистрирует вкладку. Содержимое создастся при первом показе."""
        if key in self._factories:
            logger.warning(f"вкладка с ключом {key!r} уже существует")
            return

        self._factories[key] = factory

        btn = ctk.CTkButton(
            self._tab_bar,
            text=label,
            height=_TAB_HEIGHT,
            corner_radius=SURFACE_RADIUS,
            fg_color=SURFACE_BG,
            hover_color=SURFACE_HOVER,
            text_color=SURFACE_TEXT,
            font=get_font(_FONT_SIZE, "bold"),
            command=lambda k=key: self.show(k),
        )
        self._buttons[key] = btn

        btn.grid(
            row=0,
            column=len(self._buttons) - 1,
            sticky="w",
            padx=(0, _TAB_PADX_RIGHT),
            pady=(0, _TAB_PADY_BOTTOM),
        )

        self._last_layout = []
        self._last_applied_width = 0
        self._schedule_reflow()

    def get_view(self, key: str) -> ctk.CTkFrame | None:
        """Возвращает уже созданный view или None."""
        return self._views.get(key)

    def show(self, key: str) -> None:
        if key not in self._factories:
            logger.warning(
                f"попытка показать неизвестную вкладку: {key!r}"
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
                    f"grid_forget предыдущей вкладки не удался: {exc!r}"
                )

        view.grid(row=0, column=0, sticky="nsew")
        self._current_view = view
        self._current = key

        for k, btn in self._buttons.items():
            btn.configure(
                fg_color=SURFACE_ACTIVE if k == key else SURFACE_BG
            )

        self._notify_change(key)
        self._call_on_show(view, key)

    # --- Внутреннее ---

    def _create_view(self, key: str) -> ctk.CTkFrame | None:
        factory = self._factories.get(key)
        if factory is None:
            return None

        try:
            view = factory()
        except Exception as exc:
            logger.error(
                f"не удалось создать содержимое вкладки {key!r}: {exc!r}",
                exc_info=True,
            )
            view = self._make_error_view(exc)
            self._views[key] = view
            return view

        self._views[key] = view
        logger.debug(f"вкладка {key!r} создана по требованию")
        return view

    def _make_error_view(self, exc: Exception) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame,
            text="Не удалось создать содержимое вкладки",
            anchor="w",
            font=get_font(14, "bold"),
            text_color=("#a33030", "#e88080"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        ctk.CTkLabel(
            frame,
            text=f"{type(exc).__name__}: {exc}",
            anchor="w",
            justify="left",
            wraplength=800,
            text_color=("#a33030", "#e88080"),
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 16))

        return frame

    def _notify_change(self, key: str) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(key)
        except Exception as exc:
            logger.error(f"ошибка on_change для вкладки {key!r}: {exc!r}")

    @staticmethod
    def _call_on_show(view: ctk.CTkFrame, key: str) -> None:
        on_show = getattr(view, "on_show", None)
        if not callable(on_show):
            return
        try:
            on_show()
        except Exception as exc:
            logger.error(f"ошибка on_show вкладки {key!r}: {exc!r}")

    # --- Flow layout ---

    def _on_tab_bar_configure(self, event=None) -> None:
        if self._in_reflow:
            return
        if event is not None:
            if abs(event.width - self._last_bar_width) < _MIN_WIDTH_DELTA:
                return
            self._last_bar_width = event.width
        self._schedule_reflow()

    def _schedule_reflow(self) -> None:
        if self._reflow_job is not None:
            try:
                self.after_cancel(self._reflow_job)
            except Exception as exc:
                logger.debug(f"after_cancel для reflow не удался: {exc!r}")
        self._reflow_job = self.after(_REFLOW_DELAY_MS, self._reflow)

    def _reflow(self) -> None:
        self._reflow_job = None
        if not self._buttons:
            return

        t0 = time.perf_counter()

        try:
            available = self._tab_bar.winfo_width()
        except Exception as exc:
            logger.debug(
                f"не удалось получить ширину панели вкладок: {exc!r}"
            )
            return

        if available <= 1:
            return

        if abs(available - self._last_applied_width) < _MIN_WIDTH_DELTA:
            return

        buttons = list(self._buttons.values())
        keys = list(self._buttons.keys())
        gap = _TAB_PADX_RIGHT

        rows: list[list[str]] = []
        current_row: list[str] = []
        current_width = 0

        for key, btn in zip(keys, buttons):
            try:
                btn_width = btn.winfo_reqwidth()
            except Exception:
                btn_width = 100

            if not current_row:
                current_row = [key]
                current_width = btn_width
                continue

            needed = current_width + gap + btn_width
            if needed > available:
                rows.append(current_row)
                current_row = [key]
                current_width = btn_width
            else:
                current_row.append(key)
                current_width = needed

        if current_row:
            rows.append(current_row)

        if rows == self._last_layout:
            self._last_applied_width = available
            return

        self._in_reflow = True
        try:
            for row_idx, row in enumerate(rows):
                is_last = row_idx == len(rows) - 1
                for col_idx, key in enumerate(row):
                    btn = self._buttons[key]
                    try:
                        btn.grid(
                            row=row_idx,
                            column=col_idx,
                            sticky="w",
                            padx=(0, gap),
                            pady=(0, 0 if is_last else _TAB_PADY_BOTTOM),
                        )
                    except Exception as exc:
                        logger.debug(
                            f"grid_configure вкладки не удался: {exc!r}"
                        )
        finally:
            self._in_reflow = False

        self._last_layout = rows
        self._last_applied_width = available

        elapsed_ms = (time.perf_counter() - t0) * 1000
        if elapsed_ms > _DEBUG_SLOW_MS:
            logger.debug(
                f"[SectionTabs] _reflow {elapsed_ms:.1f} мс, "
                f"доступно={available}, вкладок={len(buttons)}, "
                f"рядов={len(rows)}"
            )
