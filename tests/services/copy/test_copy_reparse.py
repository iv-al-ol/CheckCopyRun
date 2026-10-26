"""Тесты пропуска reparse points в copy.

`_CopyWorker._collect_files` не должен заходить в junction /
symlink в source: содержимое может вести куда угодно (в т.ч.
рекурсивно в себя), а `list_user_files` и mirror их тоже
пропускают. Без фильтра copy копировал бы содержимое, а
state_after — нет, и destination разошёлся бы с ожидаемым
состоянием.

`is_reparse_point` использует `stat(follow_symlinks=False)`
(эквивалент `lstat`): обычный `stat()` на Windows следует по
reparse point'у и возвращает атрибуты цели — флага
`FILE_ATTRIBUTE_REPARSE_POINT` в них нет, и функция всегда
возвращала False. Прямые тесты на `is_reparse_point` ниже
фиксируют это поведение отдельно.

Junction создаём через `mklink /J`: работает без прав
администратора на NTFS. Если ОС не даёт — skip.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from services.common.copy_constants import CCRUN_DIR_NAME

_WINDOWS = sys.platform == "win32"

pytestmark = pytest.mark.skipif(
    not _WINDOWS, reason="Windows-only",
)


def _try_make_junction(link: Path, target: Path) -> bool:
    """Создаёт junction link → target. True при успехе.

    Вывод `cmd mklink` не читаем: на русской Windows он в
    CP866, а `text=True` декодировал бы как utf-8 → падение
    в reader-потоке `subprocess` и предупреждение pytest.
    Нам нужен только `returncode`.
    """
    try:
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "cmd", "/c", "mklink", "/J",
                str(link), str(target),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _cleanup_junction(link: Path) -> None:
    try:
        link.rmdir()
    except OSError:
        pass


# --- Junction в корне source ---

def test_junction_in_source_root_is_skipped(
    src, dst, run_copy,
):
    """Junction в корне source не копируется."""
    (src / "a.txt").write_text("hello")

    outside = src.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")

    link = src / "linked"
    if not _try_make_junction(link, outside):
        pytest.skip("mklink /J недоступен")

    try:
        r = run_copy(src, dst, create_backup=True)

        assert r.total == 1
        assert r.copied == 1
        assert r.errors == 0
        assert (dst / "a.txt").read_text() == "hello"
        assert not (dst / "linked").exists()
        assert not (dst / "linked" / "secret.txt").exists()
    finally:
        _cleanup_junction(link)


# --- Junction в подпапке source ---

def test_junction_in_nested_dir_is_skipped(
    src, dst, run_copy,
):
    """Junction в подпапке source тоже не обходится."""
    (src / "sub").mkdir()
    (src / "sub" / "a.txt").write_text("hello")

    outside = src.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")

    link = src / "sub" / "linked"
    if not _try_make_junction(link, outside):
        pytest.skip("mklink /J недоступен")

    try:
        r = run_copy(src, dst, create_backup=True)

        assert r.total == 1
        assert r.copied == 1
        assert (dst / "sub" / "a.txt").read_text() == "hello"
        assert not (dst / "sub" / "linked").exists()
        assert not (dst / "sub" / "linked" / "secret.txt").exists()
    finally:
        _cleanup_junction(link)


# --- Согласованность state_after ---

def test_state_after_does_not_include_junction_files(
    src, dst, run_copy,
):
    """state_after согласован с копированием: файлов junction
    в нём нет."""
    (src / "a.txt").write_text("hello")

    outside = src.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")

    link = src / "linked"
    if not _try_make_junction(link, outside):
        pytest.skip("mklink /J недоступен")

    try:
        r = run_copy(src, dst, create_backup=True)

        assert r.state_after_path is not None
        data = json.loads(
            Path(r.state_after_path).read_text(encoding="utf-8")
        )
        paths = {f["path"] for f in data["files"]}
        assert paths == {"a.txt"}
    finally:
        _cleanup_junction(link)


# --- Junction не блокирует обычное копирование ---

def test_junction_does_not_break_rest_of_copy(
    src, dst, run_copy,
):
    """Junction игнорируется, остальные файлы копируются."""
    (src / "a.txt").write_text("hello")
    (src / "b.txt").write_text("world")

    outside = src.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")

    link = src / "linked"
    if not _try_make_junction(link, outside):
        pytest.skip("mklink /J недоступен")

    try:
        r = run_copy(src, dst, create_backup=True)

        assert r.total == 2
        assert r.copied == 2
        assert (dst / "a.txt").read_text() == "hello"
        assert (dst / "b.txt").read_text() == "world"
    finally:
        _cleanup_junction(link)


# --- !CCRun в источнике по-прежнему исключается ---

def test_ccrun_still_excluded(src, dst, run_copy):
    """Фильтр reparse points не ломает фильтр !CCRun."""
    (src / CCRUN_DIR_NAME).mkdir()
    (src / CCRUN_DIR_NAME / "meta.txt").write_text("meta")
    (src / "a.txt").write_text("hello")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 1
    assert r.copied == 1
    assert not (dst / CCRUN_DIR_NAME / "meta.txt").exists()


# --- Прямой тест is_reparse_point ---

def test_is_reparse_point_true_for_junction(tmp_path):
    """Junction детектируется как reparse point.

    Регресс-тест: раньше `stat()` следовал по junction и
    возвращал атрибуты цели — флага REPARSE_POINT в них не
    было, и функция всегда возвращала False.
    """
    from services.copy.mirror_check import is_reparse_point

    target = tmp_path / "target"
    target.mkdir()

    link = tmp_path / "link"
    if not _try_make_junction(link, target):
        pytest.skip("mklink /J недоступен")

    try:
        assert is_reparse_point(str(link)) is True
    finally:
        _cleanup_junction(link)


def test_is_reparse_point_false_for_regular_dir(tmp_path):
    from services.copy.mirror_check import is_reparse_point

    d = tmp_path / "regular"
    d.mkdir()

    assert is_reparse_point(str(d)) is False


def test_is_reparse_point_false_for_regular_file(tmp_path):
    from services.copy.mirror_check import is_reparse_point

    f = tmp_path / "file.txt"
    f.write_text("hello")

    assert is_reparse_point(str(f)) is False


def test_is_reparse_point_false_for_missing(tmp_path):
    from services.copy.mirror_check import is_reparse_point

    assert is_reparse_point(
        str(tmp_path / "does_not_exist"),
    ) is False
