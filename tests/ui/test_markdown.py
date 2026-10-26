"""Тесты разбора README.md — без tkinter."""

from __future__ import annotations

from ui.markdown import (
    KIND_BLANK,
    KIND_BULLET,
    KIND_CODE,
    KIND_H1,
    KIND_H2,
    KIND_H3,
    KIND_TABLE,
    clean_inline,
    parse_markdown,
    plain_text,
)


def _kinds(blocks):
    return [b.kind for b in blocks]


def _texts(blocks):
    return [b.text for b in blocks]


# --- Заголовки ---

def test_heading_levels():
    blocks = parse_markdown("# Один\n## Два\n### Три\n#### Четыре")
    assert _kinds(blocks) == [KIND_H1, KIND_H2, KIND_H3, KIND_H3]
    assert _texts(blocks) == ["Один", "Два", "Три", "Четыре"]


def test_heading_keeps_text_after_hashes():
    blocks = parse_markdown("## Раздел с # внутри")
    assert blocks[0].text == "Раздел с # внутри"


# --- Списки ---

def test_bullets_use_dash_and_asterisk():
    blocks = parse_markdown("- один\n* два\n+ три")
    assert _kinds(blocks) == [KIND_BULLET] * 3
    assert _texts(blocks) == ["• один", "• два", "• три"]


def test_empty_bullet_dropped():
    blocks = parse_markdown("- \n- текст")
    assert _texts(blocks) == ["• текст"]


# --- Блоки кода ---

def test_code_block_kept_verbatim():
    src = "```bat\nuv sync\nuv run main.py\n```"
    blocks = parse_markdown(src)
    assert _kinds(blocks) == [KIND_CODE, KIND_CODE]
    assert _texts(blocks) == ["uv sync", "uv run main.py"]


def test_code_block_markup_not_stripped():
    blocks = parse_markdown("```text\n**не жирный**\n```")
    assert blocks[0].text == "**не жирный**"


# --- Таблицы ---

def test_table_rule_line_skipped():
    src = "| Путь | Что там |\n|---|---|\n| a | b |"
    blocks = parse_markdown(src)
    assert _kinds(blocks) == [KIND_TABLE, KIND_TABLE]
    assert blocks[0].text == "| Путь | Что там |"
    assert blocks[1].text == "| a | b |"


# --- Inline ---

def test_clean_inline_bold_and_code():
    assert clean_inline("**жирный** и `код`") == "жирный и код"


def test_clean_inline_link_with_label():
    assert (
        clean_inline("см. [uv](https://example.com)")
        == "см. uv (https://example.com)"
    )


def test_clean_inline_bare_url():
    assert clean_inline("[https://a.b](https://a.b)") == "https://a.b"


def test_clean_inline_image_removed():
    assert clean_inline("до ![alt](img.png) после") == "до после"


def test_clean_inline_keeps_snake_case():
    """Одиночные подчёркивания внутри слов не считаются разметкой."""
    assert clean_inline("hash_cache_enabled") == "hash_cache_enabled"


# --- Пустые строки ---

def test_blank_lines_collapsed():
    blocks = parse_markdown("a\n\n\n\nb")
    assert _kinds(blocks) == ["body", KIND_BLANK, "body"]


def test_no_leading_or_trailing_blank():
    blocks = parse_markdown("\n\nтекст\n\n")
    assert _kinds(blocks) == ["body"]


def test_empty_document():
    assert parse_markdown("") == []


# --- Прочее ---

def test_quote_line():
    blocks = parse_markdown("> цитата")
    assert blocks[0].kind == "quote"
    assert blocks[0].text == "цитата"


def test_plain_text_has_no_markup():
    blocks = parse_markdown("# Заголовок\n\n- **жирный** пункт")
    result = plain_text(blocks)
    assert "#" not in result
    assert "**" not in result
    assert "жирный пункт" in result


def test_crlf_input():
    blocks = parse_markdown("# Заголовок\r\n\r\nтекст")
    assert _kinds(blocks) == [KIND_H1, KIND_BLANK, "body"]
