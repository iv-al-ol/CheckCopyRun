"""Тесты длинных путей в модели Profile.

Методы `has_*` / `can_*` используют `long_io` вместо
`os.path.*`: без этого на путях ≥ 260 символов они всегда
возвращали False, и кнопка «Запустить приложение» была
недоступна, хотя копирование работало.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core import long_io
from core.models import Profile

_WINDOWS = sys.platform == "win32"

pytestmark = pytest.mark.skipif(
    not _WINDOWS, reason="Windows-only",
)


def _make_deep_root(tmp_path: Path, prefix: str) -> Path:
    """Создаёт дерево длиной ≥ 260 символов."""
    base = tmp_path / prefix
    name = "a" * 60
    deep = base
    for _ in range(4):
        deep = deep / name
    long_io.makedirs(str(deep), exist_ok=True)
    assert len(str(deep)) >= 260, (
        f"Путь короткий: {len(str(deep))} ({deep})"
    )
    return deep


def _write_file(path: Path, content: bytes = b"MZ") -> None:
    with long_io.open(str(path), "wb") as f:
        f.write(content)


# --- has_source_and_dest ---

def test_has_source_and_dest_long(tmp_path):
    src = _make_deep_root(tmp_path, "src")
    dst = _make_deep_root(tmp_path, "dst")

    p = Profile(source=str(src), destination=str(dst))

    assert p.has_source_and_dest() is True


def test_has_source_and_dest_missing_destination(tmp_path):
    src = _make_deep_root(tmp_path, "src")
    missing = _make_deep_root(tmp_path, "missing") / "nope"

    p = Profile(source=str(src), destination=str(missing))

    assert p.has_source_and_dest() is False


# --- can_copy ---

def test_can_copy_long(tmp_path):
    src = _make_deep_root(tmp_path, "src")
    dst = _make_deep_root(tmp_path, "dst")

    p = Profile(source=str(src), destination=str(dst))

    assert p.can_copy() is True


def test_can_copy_missing_source(tmp_path):
    missing = _make_deep_root(tmp_path, "src") / "nope"
    dst = _make_deep_root(tmp_path, "dst")

    p = Profile(source=str(missing), destination=str(dst))

    assert p.can_copy() is False


# --- has_exe_in_source / has_exe_in_destination ---

def test_has_exe_in_source_long(tmp_path):
    src = _make_deep_root(tmp_path, "src")
    _write_file(src / "app.exe")

    p = Profile(source=str(src), exe_relative="app.exe")

    assert p.has_exe_in_source() is True


def test_has_exe_in_source_missing(tmp_path):
    src = _make_deep_root(tmp_path, "src")

    p = Profile(source=str(src), exe_relative="app.exe")

    assert p.has_exe_in_source() is False


def test_has_exe_in_destination_long(tmp_path):
    src = _make_deep_root(tmp_path, "src")
    dst = _make_deep_root(tmp_path, "dst")
    _write_file(dst / "app.exe")

    p = Profile(
        source=str(src),
        destination=str(dst),
        exe_relative="app.exe",
    )

    assert p.has_exe_in_destination() is True


def test_has_exe_in_destination_missing(tmp_path):
    src = _make_deep_root(tmp_path, "src")
    dst = _make_deep_root(tmp_path, "dst")

    p = Profile(
        source=str(src),
        destination=str(dst),
        exe_relative="app.exe",
    )

    assert p.has_exe_in_destination() is False


# --- can_run ---

def test_can_run_long(tmp_path):
    src = _make_deep_root(tmp_path, "src")
    dst = _make_deep_root(tmp_path, "dst")
    _write_file(src / "app.exe")
    _write_file(dst / "app.exe")

    p = Profile(
        source=str(src),
        destination=str(dst),
        exe_relative="app.exe",
    )

    assert p.can_run() is True


def test_can_run_without_exe(tmp_path):
    src = _make_deep_root(tmp_path, "src")
    dst = _make_deep_root(tmp_path, "dst")

    p = Profile(
        source=str(src),
        destination=str(dst),
        exe_relative="app.exe",
    )

    assert p.can_run() is False


# --- Короткие пути: поведение не изменилось ---

def test_short_paths_unchanged(src, dst):
    (src / "app.exe").write_bytes(b"MZ")
    (dst / "app.exe").write_bytes(b"MZ")

    p = Profile(
        source=str(src),
        destination=str(dst),
        exe_relative="app.exe",
    )

    assert p.has_source_and_dest() is True
    assert p.can_copy() is True
    assert p.has_exe_in_source() is True
    assert p.has_exe_in_destination() is True
    assert p.can_run() is True


def test_empty_paths_safe():
    p = Profile()
    assert p.has_source_and_dest() is False
    assert p.can_copy() is False
    assert p.has_exe_in_source() is False
    assert p.has_exe_in_destination() is False
    assert p.can_run() is False
