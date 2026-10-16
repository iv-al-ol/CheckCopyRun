"""Буфер обмена для CTkEntry и CTkTextbox.

CustomTkinter переопределяет стандартные привязки Ctrl+C/V/X/A
у нативных Entry и Text. Навесить свой bind недостаточно — событие
поглощается классовым обработчиком раньше нашего.

Решение: собственный тег CustomClipboardFix в bindtags, вставленный
перед классовым тегом. Обработчик на этом теге срабатывает первым.

Сочетания распознаются по event.keycode (VK-код Windows), а не по
keysym — это даёт независимость от раскладки (RU / EN).
"""

import tkinter as tk

from utils.logger import get_logger

logger = get_logger(__name__)

_BIND_TAG = "CustomClipboardFix"
_MAX_SEARCH_DEPTH = 5

# Биты модификаторов в event.state.
_STATE_SHIFT = 0x0001
_STATE_CTRL = 0x0004

# VK-коды Windows.
_VK_A = 65
_VK_C = 67
_VK_INSERT = 45
_VK_V = 86
_VK_X = 88
_VK_DELETE = 46

_tag_registered = False


# --- Поиск внутреннего виджета ---

def _describe_widget(widget) -> str:
    try:
        cls_name = type(widget).__name__
        winfo_class = widget.winfo_class()
        name = str(widget)
    except Exception as exc:
        return f"<описание недоступно: {exc!r}>"
    return f"{cls_name}(winfo_class={winfo_class!r}, name={name!r})"


def _dump_ctk_internals(widget) -> None:
    logger.warning(
        "clipboard: не найден внутренний Entry/Text у %s",
        _describe_widget(widget),
    )

    try:
        attrs = [
            a for a in dir(widget)
            if a.startswith("_") and not a.startswith("__")
        ]
    except Exception as exc:
        logger.warning("clipboard: список атрибутов недоступен: %r", exc)
        attrs = []

    interesting: list[str] = []
    for attr in attrs:
        try:
            value = getattr(widget, attr, None)
        except Exception as exc:
            logger.debug(
                "clipboard: getattr(%r) упал: %r", attr, exc,
            )
            continue
        if value is None:
            continue
        type_name = type(value).__name__
        if type_name in ("Text", "Entry", "Frame", "Canvas", "Toplevel"):
            interesting.append(f"{attr}={type_name}")

    if interesting:
        logger.warning(
            "clipboard: интересные атрибуты — %s",
            ", ".join(interesting),
        )

    logger.warning(
        "clipboard: обход детей (до глубины %d):", _MAX_SEARCH_DEPTH,
    )
    _dump_children(widget, depth=1)


def _dump_children(widget, depth: int) -> None:
    if depth > _MAX_SEARCH_DEPTH:
        return
    try:
        children = widget.winfo_children()
    except Exception as exc:
        logger.warning("clipboard: winfo_children упал: %r", exc)
        return

    if not children:
        logger.warning(
            "clipboard: %sнет детей у %s",
            "  " * depth, _describe_widget(widget),
        )
        return

    for child in children:
        logger.warning(
            "clipboard: %s%s", "  " * depth, _describe_widget(child),
        )
        _dump_children(child, depth + 1)


def _search_in_children(widget, depth: int) -> object | None:
    if depth > _MAX_SEARCH_DEPTH:
        return None

    try:
        children = widget.winfo_children()
    except Exception as exc:
        logger.debug("clipboard: winfo_children упал: %r", exc)
        return None

    for child in children:
        if isinstance(child, (tk.Entry, tk.Text)):
            logger.debug(
                "clipboard: найден внутренний виджет на глубине %d: %s",
                depth, _describe_widget(child),
            )
            return child
        found = _search_in_children(child, depth + 1)
        if isinstance(found, (tk.Entry, tk.Text)):
            return found

    return None


def _find_inner_widget(widget) -> object:
    if isinstance(widget, (tk.Entry, tk.Text)):
        return widget

    for attr in ("_entry", "_textbox", "_text"):
        inner = getattr(widget, attr, None)
        if isinstance(inner, (tk.Entry, tk.Text)):
            logger.debug(
                "clipboard: у %s найден внутренний виджет по атрибуту %r: %s",
                type(widget).__name__, attr, _describe_widget(inner),
            )
            return inner

    found = _search_in_children(widget, depth=1)
    if isinstance(found, (tk.Entry, tk.Text)):
        return found

    _dump_ctk_internals(widget)
    return widget


# --- Универсальные операции над выделением ---

def _has_selection(widget) -> bool:
    """Есть ли выделение. Работает и для Entry, и для Text."""
    if isinstance(widget, tk.Text):
        try:
            return bool(widget.tag_ranges("sel"))
        except tk.TclError as exc:
            logger.debug("clipboard: tag_ranges(sel): %r", exc)
            return False
    try:
        return bool(widget.select_present())
    except tk.TclError as exc:
        logger.debug("clipboard: select_present(): %r", exc)
        return False


def _get_selection(widget) -> str:
    """Возвращает выделенный текст или пустую строку."""
    if isinstance(widget, tk.Text):
        try:
            return widget.get("sel.first", "sel.last")
        except tk.TclError as exc:
            logger.debug("clipboard: get(sel): %r", exc)
            return ""
    try:
        return widget.selection_get()
    except tk.TclError as exc:
        logger.debug("clipboard: selection_get(): %r", exc)
        return ""


def _delete_selection(widget) -> None:
    """Удаляет выделенный текст, если он есть."""
    if not _has_selection(widget):
        return
    try:
        widget.delete("sel.first", "sel.last")
    except tk.TclError as exc:
        logger.debug("clipboard: удаление выделения не удалось: %r", exc)


# --- Операции над буфером ---

def _paste(widget) -> str:
    """Вставка из буфера обмена."""
    try:
        text = widget.clipboard_get()
    except tk.TclError as exc:
        logger.debug("clipboard: _paste — буфер пуст: %r", exc)
        return "break"

    if not text:
        return "break"

    _delete_selection(widget)

    try:
        widget.insert("insert", text)
    except tk.TclError as exc:
        logger.error("clipboard: _paste — insert не удалось: %r", exc)

    return "break"


def _copy(widget) -> str:
    """Копирование выделенного текста в буфер."""
    text = _get_selection(widget)
    if not text:
        logger.debug("clipboard: _copy — нет выделения")
        return "break"

    try:
        widget.clipboard_clear()
        widget.clipboard_append(text)
        logger.debug(
            "clipboard: _copy — скопировано %d символов", len(text),
        )
    except tk.TclError as exc:
        logger.debug("clipboard: _copy не удалось: %r", exc)

    return "break"


def _cut(widget) -> str:
    """Копирует выделенное и удаляет его."""
    _copy(widget)
    _delete_selection(widget)
    return "break"


def _select_all(widget) -> str:
    """Выделяет всё содержимое."""
    if isinstance(widget, tk.Text):
        try:
            widget.tag_add("sel", "1.0", "end")
        except tk.TclError as exc:
            logger.debug("clipboard: tag_add не удался: %r", exc)
    else:
        try:
            widget.select_range(0, "end")
        except tk.TclError as exc:
            logger.debug("clipboard: select_range не удался: %r", exc)

    try:
        widget.icursor("end")
    except tk.TclError as exc:
        logger.debug("clipboard: icursor(end): %r", exc)

    return "break"


# --- Обработчик клавиш ---

def _on_key(event):
    state = event.state
    keycode = event.keycode

    if state & _STATE_CTRL:
        if keycode == _VK_V:
            return _paste(event.widget)
        if keycode == _VK_C:
            return _copy(event.widget)
        if keycode == _VK_X:
            return _cut(event.widget)
        if keycode == _VK_A:
            return _select_all(event.widget)
        if keycode == _VK_INSERT:
            return _copy(event.widget)
        return None

    if state & _STATE_SHIFT:
        if keycode == _VK_INSERT:
            return _paste(event.widget)
        if keycode == _VK_DELETE:
            return _cut(event.widget)

    return None


# --- Установка тега и биндингов ---

def _ensure_tag_registered(anchor) -> None:
    global _tag_registered
    if _tag_registered:
        return

    try:
        anchor.bind_class(_BIND_TAG, "<Key>", _on_key)
        _tag_registered = True
        logger.debug("clipboard: тег CustomClipboardFix зарегистрирован")
    except Exception as exc:
        logger.error("clipboard: не удалось зарегистрировать тег: %r", exc)


def _attach_tag(inner) -> None:
    try:
        current = tuple(inner.bindtags())
    except Exception as exc:
        logger.debug("clipboard: bindtags не читается: %r", exc)
        return

    if _BIND_TAG in current:
        return

    try:
        widget_name = str(inner)
    except Exception as exc:
        logger.debug("clipboard: str(widget) не сработал: %r", exc)
        widget_name = ""

    new_tags = list(current)
    if widget_name and widget_name in new_tags:
        idx = new_tags.index(widget_name)
        new_tags.insert(idx + 1, _BIND_TAG)
    else:
        new_tags.insert(0, _BIND_TAG)

    try:
        inner.bindtags(tuple(new_tags))
        logger.debug(
            "clipboard: bindtags для %s (%s): %s",
            type(inner).__name__, widget_name, inner.bindtags(),
        )
    except Exception as exc:
        logger.error("clipboard: не удалось установить bindtags: %r", exc)


def enable_clipboard(widget) -> None:
    """Включает буфер обмена для CTkEntry или CTkTextbox."""
    inner = _find_inner_widget(widget)

    if not isinstance(inner, (tk.Entry, tk.Text)):
        logger.error(
            "clipboard: для %s не удалось найти нативный Entry/Text — "
            "привязка не установлена",
            type(widget).__name__,
        )
        return

    _ensure_tag_registered(inner)
    _attach_tag(inner)
