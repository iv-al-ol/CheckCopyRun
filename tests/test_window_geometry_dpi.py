"""Тесты DPI-логики геометрии окна.

Проверяются чистые функции: пересчёт виртуального экрана в
логические пиксели, конвертация геометрии и клампинг минимума
по рабочей области. Tkinter не требуется — окно подменяется
заглушкой.
"""

from __future__ import annotations

import pytest

from config.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from ui import window_geometry


class _FakeWindow:
    """Минимальная заглушка окна для чистых функций."""

    def __init__(
        self,
        *,
        scaling: float = 1.0,
        width: int = 1000,
        height: int = 600,
        x: int = 100,
        y: int = 50,
        screen_w: int = 1920,
        screen_h: int = 1080,
    ):
        self._scaling = scaling
        self._w = width
        self._h = height
        self._x = x
        self._y = y
        self._sw = screen_w
        self._sh = screen_h
        self.geometry_value: str | None = None

    def winfo_width(self) -> int:
        return self._w

    def winfo_height(self) -> int:
        return self._h

    def winfo_x(self) -> int:
        return self._x

    def winfo_y(self) -> int:
        return self._y

    def winfo_screenwidth(self) -> int:
        return self._sw

    def winfo_screenheight(self) -> int:
        return self._sh

    def geometry(self, value: str) -> None:
        self.geometry_value = value


@pytest.fixture
def patch_scaling(monkeypatch):
    """Подменяет DPI-масштаб окна."""

    def _apply(scaling: float) -> None:
        monkeypatch.setattr(
            window_geometry, "get_dpi_scaling", lambda _w: scaling,
        )

    return _apply


@pytest.fixture
def patch_virtual_screen(monkeypatch):
    """Подменяет физический размер виртуального экрана."""

    def _apply(rect: tuple[int, int, int, int] | None) -> None:
        monkeypatch.setattr(
            window_geometry,
            "get_virtual_screen_physical",
            lambda: rect,
        )

    return _apply


@pytest.fixture
def patch_work_area(monkeypatch):
    """Подменяет рабочую область (физические пиксели)."""

    def _apply(rect: tuple[int, int] | None) -> None:
        def _fake(_window):
            if rect is None:
                return None
            scaling = window_geometry.get_dpi_scaling(_window) or 1.0
            return int(rect[0] / scaling), int(rect[1] / scaling)

        monkeypatch.setattr(
            window_geometry, "get_work_area_logical", _fake,
        )

    return _apply


# --- parse_geometry ---

def test_parse_geometry_ok():
    assert window_geometry.parse_geometry("900x560+10+20") == (
        900, 560, 10, 20,
    )


def test_parse_geometry_negative_coords():
    assert window_geometry.parse_geometry("800x600+-1920+0") == (
        800, 600, -1920, 0,
    )


@pytest.mark.parametrize(
    "value",
    ["", "abc", "900x560", "900x560+10", "+10+20"],
)
def test_parse_geometry_invalid(value):
    assert window_geometry.parse_geometry(value) is None


# --- is_inside_virtual_screen ---

@pytest.mark.parametrize("scaling", [1.0, 1.25, 1.5, 2.0])
def test_window_inside_is_visible(
    patch_virtual_screen, scaling,
):
    patch_virtual_screen((0, 0, 1920, 1080))
    # Логический экран: 1920/scaling на 1080/scaling.
    assert window_geometry.is_inside_virtual_screen(
        0, 0, 400, 300, scaling,
    )


@pytest.mark.parametrize("scaling", [1.0, 1.5, 2.0])
def test_window_far_right_is_hidden(
    patch_virtual_screen, scaling,
):
    patch_virtual_screen((0, 0, 1920, 1080))
    # Координата заведомо правее логической ширины экрана.
    far_x = int(1920 / scaling) + 500
    assert not window_geometry.is_inside_virtual_screen(
        far_x, 0, 400, 300, scaling,
    )


def test_unknown_screen_assumes_visible(patch_virtual_screen):
    patch_virtual_screen(None)
    assert window_geometry.is_inside_virtual_screen(
        99999, 99999, 400, 300, 1.0,
    )


@pytest.mark.parametrize("scaling", [1.0, 1.5, 2.0])
def test_partial_overlap_counts_as_visible(
    patch_virtual_screen, scaling,
):
    patch_virtual_screen((0, 0, 1920, 1080))
    logical_w = int(1920 / scaling)
    # Окно свисает вправо, но перекрытие больше _MIN_VISIBLE_PX.
    x = logical_w - 150
    assert window_geometry.is_inside_virtual_screen(
        x, 0, 400, 300, scaling,
    )


# --- capture_geometry ---

@pytest.mark.parametrize(
    ("scaling", "expected"),
    [
        (1.0, "1000x600+100+50"),
        (1.25, "800x480+80+40"),
        (1.5, "667x400+67+33"),
        (2.0, "500x300+50+25"),
    ],
)
def test_capture_geometry_uses_logical_px(
    patch_scaling, scaling, expected,
):
    patch_scaling(scaling)
    window = _FakeWindow(scaling=scaling)
    assert window_geometry.capture_geometry(window) == expected


def test_capture_geometry_unmapped_returns_none(patch_scaling):
    patch_scaling(1.0)
    window = _FakeWindow(width=1, height=1)
    assert window_geometry.capture_geometry(window) is None


def test_capture_geometry_roundtrip_at_150(patch_scaling):
    """Сохранённая логическая геометрия не растёт при перезапуске."""
    patch_scaling(1.5)
    window = _FakeWindow(
        scaling=1.5, width=1500, height=900, x=300, y=150,
    )
    saved = window_geometry.capture_geometry(window)
    assert saved == "1000x600+200+100"

    restored = window_geometry.parse_geometry(saved or "")
    assert restored == (1000, 600, 200, 100)


# --- effective_min_size ---

def test_effective_min_size_normal_screen(
    patch_scaling, patch_work_area,
):
    patch_scaling(1.0)
    patch_work_area((1920, 1040))
    window = _FakeWindow()
    assert window_geometry.effective_min_size(window) == (
        WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT,
    )


def test_effective_min_size_small_high_dpi_screen(
    patch_scaling, patch_work_area,
):
    """1366x768 при 150% даёт 911x485 логических — высота ужимается."""
    patch_scaling(1.5)
    patch_work_area((1366, 728))
    window = _FakeWindow()
    width, height = window_geometry.effective_min_size(window)
    # Ширина 911 больше номинала — остаётся 900.
    assert width == WINDOW_MIN_WIDTH
    # Высота 485 меньше номинала 560 — ужимается под рабочую область.
    assert height == int(728 / 1.5)
    assert height < WINDOW_MIN_HEIGHT


def test_effective_min_size_no_work_area(
    patch_scaling, patch_work_area,
):
    patch_scaling(2.0)
    patch_work_area(None)
    window = _FakeWindow()
    assert window_geometry.effective_min_size(window) == (
        WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT,
    )


# --- apply_default_geometry ---

def test_apply_default_geometry_centers_in_work_area(
    patch_scaling, patch_work_area,
):
    patch_scaling(1.0)
    patch_work_area((1920, 1040))
    window = _FakeWindow()
    window_geometry.apply_default_geometry(window)
    assert window.geometry_value == "900x560+510+240"


def test_apply_default_geometry_clips_to_work_area(
    patch_scaling, patch_work_area,
):
    patch_scaling(1.0)
    patch_work_area((800, 500))
    window = _FakeWindow()
    window_geometry.apply_default_geometry(window)
    # Размер ужат до рабочей области, позиция — 0,0.
    assert window.geometry_value == "800x500+0+0"


def test_apply_default_geometry_fallback_without_work_area(
    patch_scaling, patch_work_area,
):
    patch_scaling(1.0)
    patch_work_area(None)
    window = _FakeWindow(screen_w=1920, screen_h=1080)
    window_geometry.apply_default_geometry(window)
    assert window.geometry_value == "900x560+510+260"


# --- try_restore_geometry ---

def test_try_restore_rejects_below_min(
    patch_scaling, patch_virtual_screen,
):
    patch_scaling(1.0)
    patch_virtual_screen((0, 0, 1920, 1080))
    window = _FakeWindow()
    assert not window_geometry.try_restore_geometry(
        window, "400x300+10+10",
    )
    assert window.geometry_value is None


def test_try_restore_rejects_offscreen(
    patch_scaling, patch_virtual_screen,
):
    patch_scaling(1.0)
    patch_virtual_screen((0, 0, 1920, 1080))
    window = _FakeWindow()
    assert not window_geometry.try_restore_geometry(
        window, "900x560+9000+9000",
    )
    assert window.geometry_value is None


def test_try_restore_accepts_valid(
    patch_scaling, patch_virtual_screen,
):
    patch_scaling(1.0)
    patch_virtual_screen((0, 0, 1920, 1080))
    window = _FakeWindow()
    assert window_geometry.try_restore_geometry(
        window, "1000x600+100+100",
    )
    assert window.geometry_value == "1000x600+100+100"
