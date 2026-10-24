"""Тесты helpers для длинных путей."""

from __future__ import annotations

import os
import sys

import pytest

from core.paths import (
    LONG_PATH_THRESHOLD,
    display_path,
    from_long_path,
    is_long_path,
    to_long_path,
)

_WINDOWS = sys.platform == "win32"

pytestmark = pytest.mark.skipif(
    not _WINDOWS, reason="Windows-only",
)


def test_short_path_no_prefix(tmp_path):
    p = str(tmp_path / "file.txt")
    result = to_long_path(p)
    assert not result.startswith("\\\\?\\")
    assert os.path.isabs(result)


def test_absolute_returned(tmp_path):
    p = str(tmp_path / "file.txt")
    result = to_long_path(p)
    assert os.path.isabs(result)


def test_long_path_prefixed(tmp_path):
    name = "a" * 200
    deep = tmp_path / name / name
    p = str(deep / "file.txt")
    assert len(p) >= LONG_PATH_THRESHOLD

    result = to_long_path(p)
    assert result.startswith("\\\\?\\")
    assert "\\\\?\\C:" in result or "\\\\?\\" in result


def test_already_prefixed_unchanged(tmp_path):
    p = "\\\\?\\C:\\some\\path\\file.txt"
    assert to_long_path(p) == p


def test_from_long_path_strips_prefix():
    prefixed = "\\\\?\\C:\\foo\\bar"
    assert from_long_path(prefixed) == "C:\\foo\\bar"


def test_from_long_path_strips_unc():
    prefixed = "\\\\?\\UNC\\server\\share\\foo"
    assert from_long_path(prefixed) == "\\\\server\\share\\foo"


def test_from_long_path_no_prefix():
    p = "C:\\foo\\bar"
    assert from_long_path(p) == p


def test_display_path(tmp_path):
    p = str(tmp_path / "file.txt")
    assert display_path(p) == p


def test_is_long_path_false(tmp_path):
    p = str(tmp_path / "file.txt")
    assert is_long_path(p) is False


def test_is_long_path_true(tmp_path):
    name = "a" * 200
    p = str(tmp_path / name / name / "file.txt")
    assert is_long_path(p) is True


def test_to_long_path_unc(tmp_path):
    # Не создаём реальный UNC, просто проверяем префиксацию.
    # Длинный UNC путь.
    p = (
        "\\\\server\\share\\" + "a" * 250 + "\\file.txt"
    )
    result = to_long_path(p)
    assert result.startswith("\\\\?\\UNC\\")
