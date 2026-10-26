"""Тест path_conflict_error с длинными путями."""

from __future__ import annotations

import sys

import pytest

from core.paths import path_conflict_error

_WINDOWS = sys.platform == "win32"

pytestmark = pytest.mark.skipif(
    not _WINDOWS, reason="Windows-only",
)


def test_same_long_path():
    name = "a" * 200
    base = f"C:\\{name}"
    err = path_conflict_error(base, base)
    assert err is not None
    assert "совпадают" in err


def test_inside_long_path():
    name = "a" * 200
    base = f"C:\\{name}"
    inner = f"{base}\\sub"
    err = path_conflict_error(base, inner)
    assert err is not None
    assert "внутри исходной" in err


def test_outside_long_path():
    name = "a" * 200
    p1 = f"C:\\{name}\\one"
    p2 = f"C:\\{name}\\two"
    err = path_conflict_error(p1, p2)
    assert err is None


def test_sibling_shared_prefix():
    """C:\\foo\\bar и C:\\foo\\barbaz — не вложены."""
    err = path_conflict_error(
        "C:\\foo\\bar", "C:\\foo\\barbaz",
    )
    assert err is None
