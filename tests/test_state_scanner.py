"""Тесты сканера destination → StateData."""

from __future__ import annotations

import hashlib
import os

from services.hash_cache import HashCache
from services.state_scanner import scan_destination


def test_empty_destination(tmp_path):
    data = scan_destination(str(tmp_path))
    assert data.files == []
    assert data.empty_dirs == []
    assert data.summary["files_count"] == 0
    assert data.summary["total_size"] == 0


def test_missing_destination(tmp_path):
    missing = tmp_path / "nope"
    data = scan_destination(str(missing))
    assert data.files == []
    assert data.summary["files_count"] == 0


def test_simple_files(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "b.txt").write_text("22")

    data = scan_destination(str(tmp_path))

    assert data.summary["files_count"] == 2
    assert data.summary["total_size"] == 3

    by_path = {f.path: f for f in data.files}
    assert by_path["a.txt"].sha256 == hashlib.sha256(
        b"1"
    ).hexdigest()
    assert by_path["b.txt"].size == 2


def test_nested_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.txt").write_text("x")

    data = scan_destination(str(tmp_path))

    assert len(data.files) == 1
    assert data.files[0].path == os.path.join("sub", "f.txt")


def test_empty_dirs(tmp_path):
    (tmp_path / "e1").mkdir()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "e2").mkdir()
    (tmp_path / "sub" / "f.txt").write_text("x")

    data = scan_destination(str(tmp_path))

    assert "e1" in data.empty_dirs
    assert os.path.join("sub", "e2") in data.empty_dirs
    assert "sub" not in data.empty_dirs
    assert data.summary["empty_dirs_count"] == 2


def test_nested_empty_only(tmp_path):
    """sub/e — пустой, sub — тоже по факту пустой."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "e").mkdir()

    data = scan_destination(str(tmp_path))

    assert os.path.join("sub", "e") in data.empty_dirs
    assert "sub" not in data.empty_dirs


def test_skip_ccrun(tmp_path):
    (tmp_path / "!CCRun").mkdir()
    (tmp_path / "!CCRun" / "x.json").write_text("{}")
    (tmp_path / "a.txt").write_text("x")

    data = scan_destination(str(tmp_path))

    assert len(data.files) == 1
    assert data.files[0].path == "a.txt"
    assert "!CCRun" not in data.empty_dirs


def test_skip_old_backup_dir(tmp_path):
    old = tmp_path / "!Backup_2025.01.01_00.00.00.000"
    old.mkdir()
    (old / "old.txt").write_text("x")
    (tmp_path / "a.txt").write_text("x")

    data = scan_destination(str(tmp_path))

    assert len(data.files) == 1
    assert data.files[0].path == "a.txt"


def test_ccrun_in_subdir_not_special(tmp_path):
    """!CCRun внутри подпапки — обычная пользовательская."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "!CCRun").mkdir()
    (tmp_path / "sub" / "!CCRun" / "note.txt").write_text("x")

    data = scan_destination(str(tmp_path))

    paths = {f.path for f in data.files}
    assert os.path.join("sub", "!CCRun", "note.txt") in paths


def test_hash_cache_reuse(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello")
    st = os.stat(p)
    sha = hashlib.sha256(b"hello").hexdigest()

    cache = HashCache(str(tmp_path))
    cache.put(
        "a.txt",
        size=5,
        src_mtime_ns=st.st_mtime_ns,
        dst_mtime_ns=st.st_mtime_ns,
        sha256=sha,
    )

    data = scan_destination(str(tmp_path), hash_cache=cache)
    assert data.files[0].sha256 == sha


def test_hash_cache_stale_mtime_recomputes(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello")
    st = os.stat(p)
    sha_old = hashlib.sha256(b"hello").hexdigest()

    cache = HashCache(str(tmp_path))
    cache.put(
        "a.txt",
        size=5,
        src_mtime_ns=st.st_mtime_ns - 1_000_000,
        dst_mtime_ns=st.st_mtime_ns - 1_000_000,
        sha256=sha_old,
    )

    # Меняем содержимое — хэш должен пересчитаться.
    p.write_text("new")
    data = scan_destination(str(tmp_path), hash_cache=cache)
    assert data.files[0].sha256 == hashlib.sha256(
        b"new"
    ).hexdigest()


def test_summary_fields(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "e").mkdir()

    data = scan_destination(str(tmp_path))

    assert data.summary["files_count"] == 1
    assert data.summary["empty_dirs_count"] == 1
    assert data.summary["total_size"] == 1
    assert data.summary["new_blobs_count"] == 0
    assert data.summary["new_blobs_bytes"] == 0
