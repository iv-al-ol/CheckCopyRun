"""Тесты модели выделения (без tkinter)."""

from __future__ import annotations

from services.selection_model import SelectionModel


def _model(ids: list[str] | None = None) -> SelectionModel:
    m = SelectionModel()
    m.set_items(ids or ["a", "b", "c", "d", "e"])
    return m


# --- Базовое ---

def test_empty():
    m = SelectionModel()
    assert m.get_selected() == []
    assert m.count() == 0


def test_set_items_filters_selection():
    m = _model()
    m.select_only("c")
    assert m.get_selected() == ["c"]

    m.set_items(["a", "b"])
    assert m.get_selected() == []


def test_clear():
    m = _model()
    m.select_only("b")
    m.clear()
    assert m.get_selected() == []


# --- Обычный клик ---

def test_click_single():
    m = _model()
    m.handle_click("c", ctrl=False, shift=False)
    assert m.get_selected() == ["c"]


def test_click_replaces_previous():
    m = _model()
    m.select_many(["a", "b"])
    m.handle_click("d", ctrl=False, shift=False)
    assert m.get_selected() == ["d"]


# --- Ctrl ---

def test_ctrl_adds():
    m = _model()
    m.handle_click("a", ctrl=False, shift=False)
    m.handle_click("c", ctrl=True, shift=False)
    assert m.get_selected() == ["a", "c"]


def test_ctrl_removes():
    m = _model()
    m.select_many(["a", "b", "c"])
    m.handle_click("b", ctrl=True, shift=False)
    assert m.get_selected() == ["a", "c"]


def test_ctrl_toggle_off_then_on():
    m = _model()
    m.handle_click("b", ctrl=True, shift=False)
    assert m.get_selected() == ["b"]
    m.handle_click("b", ctrl=True, shift=False)
    assert m.get_selected() == []


# --- Shift ---

def test_shift_range_forward():
    m = _model()
    m.handle_click("b", ctrl=False, shift=False)
    m.handle_click("d", ctrl=False, shift=True)
    assert m.get_selected() == ["b", "c", "d"]


def test_shift_range_backward():
    m = _model()
    m.handle_click("d", ctrl=False, shift=False)
    m.handle_click("b", ctrl=False, shift=True)
    assert m.get_selected() == ["b", "c", "d"]


def test_shift_without_anchor():
    m = _model()
    m.handle_click("c", ctrl=False, shift=True)
    assert m.get_selected() == ["c"]


def test_shift_repeated_extends_from_original_anchor():
    m = _model()
    m.handle_click("b", ctrl=False, shift=False)
    m.handle_click("d", ctrl=False, shift=True)
    assert m.get_selected() == ["b", "c", "d"]
    # Anchor обновился на d — теперь Shift-клик на e даст d..e.
    m.handle_click("e", ctrl=False, shift=True)
    assert m.get_selected() == ["d", "e"]


# --- ПКМ ---

def test_right_click_not_selected():
    m = _model()
    m.select_many(["a", "b"])
    m.handle_right_click("d")
    assert m.get_selected() == ["d"]


def test_right_click_already_selected():
    m = _model()
    m.select_many(["a", "b", "c"])
    m.handle_right_click("b")
    assert m.get_selected() == ["a", "b", "c"]


# --- Рамка ---

def test_ids_in_rect():
    m = _model()
    item_rects = {
        "a": (0, 0, 100, 40),
        "b": (0, 40, 100, 80),
        "c": (0, 80, 100, 120),
        "d": (0, 120, 100, 160),
        "e": (0, 160, 100, 200),
    }
    # Рамка пересекает b и c.
    rect = (10, 50, 90, 100)
    assert m.ids_in_rect(rect, item_rects) == ["b", "c"]


def test_ids_in_rect_partial_overlap():
    """Пересечение в 1 пиксель — это всё ещё пересечение."""
    m = _model()
    item_rects = {
        "a": (0, 0, 100, 40),
        "b": (0, 40, 100, 80),
    }
    # Query y=39..40 заходит на 1 пиксель в a, но b не задевает:
    # нижняя граница a = 40, верхняя граница b = 40, а query
    # заканчивается на 40 (не пересекает b).
    assert m.ids_in_rect((0, 39, 100, 40), item_rects) == ["a"]


def test_ids_in_rect_boundary_only():
    """Касание границей (без общей площади) — не пересечение."""
    m = _model()
    item_rects = {"a": (0, 0, 100, 40)}
    # Нижняя граница a = 40, верхняя граница query = 40 — общая
    # площадь 0, пересечения нет.
    assert m.ids_in_rect((0, 40, 100, 50), item_rects) == []


def test_ids_in_rect_empty():
    m = _model()
    item_rects = {
        "a": (0, 0, 100, 40),
    }
    assert m.ids_in_rect((200, 200, 300, 300), item_rects) == []


def test_select_many():
    m = _model()
    m.select_many(["b", "d", "zzz"])   # zzz нет в order
    assert m.get_selected() == ["b", "d"]
    assert m.count() == 2


# --- Вспомогательное ---

def test_get_selected_set():
    m = _model()
    m.select_many(["a", "c"])
    assert m.get_selected_set() == {"a", "c"}
