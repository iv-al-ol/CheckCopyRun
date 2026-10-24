"""Интеграционные тесты I/O с длинными путями."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core import long_io
from core.paths import to_long_path

_WINDOWS = sys.platform == "win32"

pytestmark = pytest.mark.skipif(
    not _WINDOWS, reason="Windows-only",
)


def _make_deep_path(tmp_path: Path) -> Path:
    """Создаёт путь > 260 символов через long_io."""
    name = "a" * 60
    deep = tmp_path
    for _ in range(4):
        deep = deep / name
    long_io.makedirs(str(deep), exist_ok=True)
    assert len(str(deep)) >= 260, f"Путь короткий: {len(str(deep))}"
    return deep


def test_makedirs_long(tmp_path):
    deep = _make_deep_path(tmp_path)
    assert long_io.isdir(str(deep))


def test_write_read_long(tmp_path):
    deep = _make_deep_path(tmp_path)
    f = deep / "file.txt"

    with long_io.open(str(f), "w", encoding="utf-8") as fh:
        fh.write("hello")

    with long_io.open(str(f), "r", encoding="utf-8") as fh:
        content = fh.read()
    assert content == "hello"


def test_copy2_long(tmp_path):
    deep = _make_deep_path(tmp_path)

    src = deep / "src.txt"
    dst = deep / "dst.txt"

    with long_io.open(str(src), "w", encoding="utf-8") as fh:
        fh.write("data")

    long_io.copy2(str(src), str(dst))

    assert long_io.isfile(str(dst))
    with long_io.open(str(dst), "r", encoding="utf-8") as fh:
        assert fh.read() == "data"


def test_remove_long(tmp_path):
    deep = _make_deep_path(tmp_path)
    f = deep / "file.txt"
    long_io.open(str(f), "w").close()
    assert long_io.exists(str(f))
    long_io.remove(str(f))
    assert not long_io.exists(str(f))


def test_walk_long(tmp_path):
    deep = _make_deep_path(tmp_path)
    f = deep / "file.txt"
    long_io.open(str(f), "w").close()

    top = to_long_path(str(tmp_path))
    found = []
    for root, dirs, names in long_io.walk(top):
        for name in names:
            found.append(name)
    assert "file.txt" in found


def test_stat_long(tmp_path):
    deep = _make_deep_path(tmp_path)
    f = deep / "file.txt"
    with long_io.open(str(f), "w", encoding="utf-8") as fh:
        fh.write("12345")
    st = long_io.stat(str(f))
    assert st.st_size == 5


def test_hash_file_long(tmp_path):
    from services.hash_cache import hash_file

    deep = _make_deep_path(tmp_path)
    f = deep / "file.txt"
    with long_io.open(str(f), "w", encoding="utf-8") as fh:
        fh.write("hello")
    h = hash_file(str(f))
    assert len(h) == 64
    assert h == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
