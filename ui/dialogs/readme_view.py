"""Встроенный просмотр README.md.

Нужен как запасной вариант: на машине может не оказаться
программы, связанной с `.md`. Тогда файл показывается прямо
в окне — с заголовками, списками, таблицами и блоками кода.

Кнопка «Открыть в программе по умолчанию» остаётся доступной,
чтобы читатель мог перейти во внешний редактор, если тот есть.
"""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from services.system.file_opener import try_open_associated
from ui.components.button import (
    VARIANT_PRIMARY,
    VARIANT_SECONDARY,
    StyledButton,
)
from ui.components.scrollable import AutoHideScrollableFrame
from ui.components.separator import make_separator
from ui.dialogs import show_error
from ui.dialogs._centering import bring_to_front, center_on_parent
from ui.dialogs._setup import setup_dialog
from ui.fonts import get_font
from ui.markdown import (
    KIND_BLANK,
    KIND_BULLET,
    KIND_CODE,
    KIND_H1,
    KIND_H2,
    KIND_H3,
    KIND_QUOTE,
    KIND_TABLE,
    MdBlock,
    parse_markdown,
)
from utils.logger import get_logger

logger = get_logger(__name__)

_DIALOG_WIDTH = 760
_DIALOG_HEIGHT = 620
_MIN_WIDTH = 560
_MIN_HEIGHT = 420

_WRAP = 660

_TITLE_FONT_SIZE = 16
_BODY_FONT_SIZE = 13
_HINT_FONT_SIZE = 11

_CODE_BG = ("gray88", "gray20")
_QUOTE_COLOR = ("gray35", "gray65")
_MUTED_COLOR = ("gray40", "gray60")

_FONT_H1 = 20
_FONT_H2 = 16
_FONT_H3 = 14


def show_readme(
    parent,
    path: str,
    parent_visible: bool = True,
) -> None:
    """Показывает README.md в отдельном окне."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        logger.exception("Не удалось прочитать README: %r", exc)
        show_error(
            parent,
            "Не удалось открыть описание",
            f"Файл не читается:\n{path}\n\n{exc}",
        )
        return
    except UnicodeDecodeError:
        try:
            text = Path(path).read_text(encoding="cp1251")
        except (OSError, UnicodeDecodeError) as exc:
            logger.exception("Кодировка README не распознана: %r", exc)
            show_error(
                parent,
                "Не удалось открыть описание",
                "Файл сохранён в неизвестной кодировке.\n\n"
                f"Путь:\n{path}",
            )
            return

    _ReadmeDialog(
        parent,
        path=path,
        text=text,
        parent_visible=parent_visible,
    ).run()


class _ReadmeDialog:
    """Окно с содержимым README и кнопками действий."""

    def __init__(
        self,
        parent,
        *,
        path: str,
        text: str,
        parent_visible: bool,
    ) -> None:
        self._parent = parent
        self._path = path
        self._text = text
        self._parent_visible = parent_visible

        self._dialog = setup_dialog(
            parent, "Описание программы", parent_visible,
        )
        self._dialog.resizable(True, True)
        self._dialog.minsize(_MIN_WIDTH, _MIN_HEIGHT)

        self._build()

    # --- Построение ---

    def _build(self) -> None:
        self._dialog.grid_columnconfigure(0, weight=1)
        self._dialog.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self._dialog, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Описание программы",
            anchor="w",
            font=get_font(_TITLE_FONT_SIZE, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text=self._path,
            anchor="w",
            text_color=_MUTED_COLOR,
            font=get_font(_HINT_FONT_SIZE),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        make_separator(self._dialog).grid(
            row=1, column=0, sticky="new", padx=20,
        )

        body = AutoHideScrollableFrame(
            self._dialog,
            fg_color="transparent",
            corner_radius=0,
        )
        body.grid(row=2, column=0, sticky="nsew", padx=20, pady=(12, 8))
        body.grid_columnconfigure(0, weight=1)

        self._body = body
        self._pending_indent = {}
        self._render(parse_markdown(self._text))

        bottom = ctk.CTkFrame(self._dialog, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 16))
        bottom.grid_columnconfigure(0, weight=1)

        StyledButton(
            bottom,
            text="Открыть в программе по умолчанию",
            variant=VARIANT_SECONDARY,
            width=250,
            command=self._open_external,
        ).grid(row=0, column=1, padx=(0, 8))

        StyledButton(
            bottom,
            text="Закрыть",
            variant=VARIANT_PRIMARY,
            width=120,
            command=self._dialog.destroy,
        ).grid(row=0, column=2)

        self._dialog.bind("<Escape>", lambda _e: self._dialog.destroy())
        self._dialog.protocol("WM_DELETE_WINDOW", self._dialog.destroy)

    def _render(self, blocks: list[MdBlock]) -> None:
        row = 0
        for block in blocks:
            widget = self._make_block(block)
            if widget is None:
                continue
            indent = self._pending_indent.get(widget, 0)
            widget.grid(
                row=row, column=0, sticky="ew",
                padx=(4 + indent, 4),
                pady=_block_pady(block.kind),
            )
            row += 1

    def _make_block(self, block: MdBlock):
        if block.kind == KIND_BLANK:
            spacer = ctk.CTkFrame(
                self._body, fg_color="transparent", height=6,
            )
            spacer.grid_propagate(False)
            return spacer

        if block.kind == KIND_CODE:
            return self._make_code_line(block.text)

        if block.kind == KIND_TABLE:
            return self._make_table_line(block.text)

        if block.kind == KIND_H1:
            return self._make_heading(block.text, _FONT_H1)

        if block.kind == KIND_H2:
            return self._make_heading(block.text, _FONT_H2)

        if block.kind == KIND_H3:
            return self._make_heading(block.text, _FONT_H3)

        if block.kind == KIND_BULLET:
            return self._make_text(
                block.text, indent=10, font_size=_BODY_FONT_SIZE,
            )

        if block.kind == KIND_QUOTE:
            return self._make_text(
                block.text,
                font_size=_BODY_FONT_SIZE,
                color=_QUOTE_COLOR,
                indent=10,
            )

        return self._make_text(
            block.text, font_size=_BODY_FONT_SIZE,
        )

    def _make_heading(self, text: str, size: int):
        label = ctk.CTkLabel(
            self._body,
            text=text,
            anchor="w",
            justify="left",
            wraplength=_WRAP,
            font=get_font(size, "bold"),
        )
        label.bind("<Configure>", _fit_wrap(label))
        return label

    def _make_text(
        self,
        text: str,
        *,
        font_size: int = _BODY_FONT_SIZE,
        color=None,
        indent: int = 0,
    ):
        options = {
            "text": text,
            "anchor": "w",
            "justify": "left",
            "wraplength": _WRAP,
            "font": get_font(font_size),
        }
        if color is not None:
            options["text_color"] = color

        label = ctk.CTkLabel(self._body, **options)
        label.bind("<Configure>", _fit_wrap(label, indent))
        self._pending_indent[label] = indent
        return label

    def _make_code_line(self, text: str):
        line = ctk.CTkLabel(
            self._body,
            text=text or " ",
            anchor="w",
            justify="left",
            wraplength=_WRAP,
            fg_color=_CODE_BG,
            corner_radius=3,
            padx=8,
            pady=2,
            font=get_font(12),
        )
        line.bind("<Configure>", _fit_wrap(line, 16))
        return line

    def _make_table_line(self, text: str):
        cells = [
            cell.strip() for cell in text.strip().strip("|").split("|")
        ]
        rendered = "   ".join(cell for cell in cells if cell)
        return self._make_text(
            rendered or text,
            font_size=_BODY_FONT_SIZE,
        )

    # --- Действия ---

    def _open_external(self) -> None:
        result = try_open_associated(self._path)
        if result.success:
            return
        show_error(
            self._dialog,
            "Не удалось открыть файл",
            f"{result.error}\n\n"
            "Содержимое уже показано в этом окне.",
            parent_visible=True,
        )

    # --- Показ ---

    def run(self) -> None:
        try:
            self._dialog.update_idletasks()
            self._dialog.deiconify()
        except Exception as exc:
            logger.debug("подготовка окна README: %r", exc)

        self._apply_size()

        center_on_parent(self._dialog, self._parent)
        bring_to_front(self._dialog, self._parent_visible)

        try:
            self._body.check_scroll_now()
        except Exception as exc:
            logger.debug("check_scroll_now: %r", exc)

        try:
            self._parent.wait_window(self._dialog)
        except Exception as exc:
            logger.debug("wait_window README: %r", exc)

    def _apply_size(self) -> None:
        """Начальный размер с поправкой на масштаб экрана."""
        try:
            scaling = ctk.ScalingTracker.get_window_dpi_scaling(
                self._dialog,
            )
        except Exception as exc:
            logger.debug("scaling README: %r", exc)
            scaling = 1.0

        if not scaling or scaling <= 0:
            scaling = 1.0

        w = round(_DIALOG_WIDTH * scaling)
        h = round(_DIALOG_HEIGHT * scaling)

        screen_w = self._dialog.winfo_screenwidth()
        screen_h = self._dialog.winfo_screenheight()
        w = min(w, max(320, screen_w - 80))
        h = min(h, max(240, screen_h - 120))

        try:
            self._dialog.wm_geometry(f"{w}x{h}")
        except Exception as exc:
            logger.debug("wm_geometry README: %r", exc)


# --- Вспомогательное ---

def _block_pady(kind: str) -> tuple[int, int]:
    if kind in (KIND_H1, KIND_H2, KIND_H3):
        return (12, 4)
    if kind == KIND_BLANK:
        return (0, 0)
    if kind == KIND_CODE:
        return (0, 1)
    return (0, 3)


def _fit_wrap(label, indent: int = 0):
    """Подгоняет перенос строк под текущую ширину колонки."""
    def handler(event) -> None:
        width = int(event.width) - indent - 8
        if width < 120:
            return
        try:
            label.configure(wraplength=width)
        except Exception as exc:
            logger.debug("wraplength: %r", exc)

    return handler
