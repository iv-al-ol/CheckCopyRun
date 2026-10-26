"""Разбор README.md для встроенного просмотра.

Полноценный Markdown здесь не нужен: задача — превратить файл
в предсказуемые строки, которые читаются в текстовом поле
без внешнего редактора. Поддерживаются заголовки, списки,
таблицы, блоки кода и простое inline-оформление (жирный,
инлайн-код, ссылки).

Модуль не зависит от tkinter — разбор тестируется отдельно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["MdBlock", "parse_markdown", "plain_text"]

# --- Виды блоков ---

KIND_H1 = "h1"
KIND_H2 = "h2"
KIND_H3 = "h3"
KIND_BODY = "body"
KIND_BULLET = "bullet"
KIND_CODE = "code"
KIND_TABLE = "table"
KIND_QUOTE = "quote"
KIND_BLANK = "blank"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_BOLD_ALT_RE = re.compile(r"__([^_]+)__")

_ITALIC_RE = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")

_BULLET_PREFIXES = ("- ", "* ", "+ ")

# Пункт списка без текста: `-` после rstrip.
_BARE_BULLETS = frozenset({"-", "*", "+"})

# Символы, из которых состоит разделительная строка таблицы.
_TABLE_RULE_CHARS = set("|-: ")


@dataclass(frozen=True)
class MdBlock:
    """Одна строка документа вместе с её ролью."""

    kind: str
    text: str = ""


def parse_markdown(text: str) -> list[MdBlock]:
    """Превращает markdown в список блоков для отображения."""
    blocks: list[MdBlock] = []
    in_code = False

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()

        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue

        if in_code:
            blocks.append(MdBlock(KIND_CODE, line))
            continue

        stripped = line.strip()

        if not stripped:
            blocks.append(MdBlock(KIND_BLANK))
            continue

        if stripped.startswith("|"):
            if _is_table_rule(stripped):
                continue
            blocks.append(MdBlock(KIND_TABLE, stripped))
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            kind = KIND_H1 if level == 1 else (
                KIND_H2 if level == 2 else KIND_H3
            )
            blocks.append(
                MdBlock(kind, clean_inline(heading.group(2))),
            )
            continue

        if stripped.startswith(_BULLET_PREFIXES):
            body = clean_inline(stripped[2:])
            if body:
                blocks.append(MdBlock(KIND_BULLET, f"• {body}"))
            continue

        if stripped in _BARE_BULLETS:
            # Пустой пункт списка — просто пропускаем.
            continue

        if stripped.startswith(">"):
            body = clean_inline(stripped.lstrip("> ").strip())
            blocks.append(MdBlock(KIND_QUOTE, body))
            continue

        blocks.append(MdBlock(KIND_BODY, clean_inline(stripped)))

    return _collapse_blank(blocks)


def plain_text(blocks: list[MdBlock]) -> str:
    """Текст блоков без разметки — для буфера обмена и тестов."""
    return "\n".join(b.text for b in blocks)


# --- Inline-оформление ---

def clean_inline(text: str) -> str:
    """Убирает markdown-разметку, оставляя читаемый текст."""
    result = _IMAGE_RE.sub("", text)
    result = _LINK_RE.sub(
        lambda m: _format_link(m.group(1), m.group(2)), result,
    )
    result = _CODE_RE.sub(r"\1", result)
    result = _BOLD_RE.sub(r"\1", result)
    result = _BOLD_ALT_RE.sub(r"\1", result)
    result = _ITALIC_RE.sub(r"\1", result)
    # После удаления картинок и ссылок могли остаться двойные
    # пробелы — в текстовом поле они выглядят как опечатка.
    return re.sub(r"[ \t]{2,}", " ", result).strip()


def _format_link(label: str, url: str) -> str:
    label = label.strip()
    url = url.strip()
    if not url:
        return label
    if not label or label == url:
        return url
    return f"{label} ({url})"


# --- Служебное ---

def _is_table_rule(line: str) -> bool:
    """True для строки `|---|---|` под шапкой таблицы."""
    return "-" in line and set(line) <= _TABLE_RULE_CHARS


def _collapse_blank(blocks: list[MdBlock]) -> list[MdBlock]:
    """Не больше одной пустой строки подряд и без пустых по краям."""
    result: list[MdBlock] = []
    for block in blocks:
        if block.kind == KIND_BLANK and (
            not result or result[-1].kind == KIND_BLANK
        ):
            continue
        result.append(block)

    while result and result[-1].kind == KIND_BLANK:
        result.pop()

    return result
