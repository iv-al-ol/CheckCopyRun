"""Тесты режима зеркала и pre-scan (CAS)."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from services.cas.blob_store import BlobStore
from services.copy.copy_service import CopyService
from services.copy.mirror_check import (
    MirrorStats,
    scan_mirror_diff,
)

# --- MirrorStats ---

def test_mirror_stats_empty():
    s = MirrorStats()
    assert s.files_ratio == 0.0
    assert s.requires_confirmation is False


def test_mirror_stats_half():
    s = MirrorStats(
        files_to_remove=["a", "b"],
        total_destination_files=4,
    )
    # 2/4 = 0.5, не больше 50% → не требует.
    assert s.requires_confirmation is False


def test_mirror_stats_more_than_half():
    s = MirrorStats(
        files_to_remove=["a", "b", "c"],
        total_destination_files=4,
    )
    # 3/4 > 0.5 → требует.
    assert s.requires_confirmation is True


def test_mirror_stats_only_dirs():
    # Удаляются только директории — confirmation не нужен.
    s = MirrorStats(
        dirs_to_remove=["old_dir"],
        total_destination_files=0,
    )
    assert s.requires_confirmation is False


# --- scan_mirror_diff ---

def test_scan_identical(src, dst):
    (src / "a.txt").write_text("1")
    (src / "b.txt").write_text("2")
    (dst / "a.txt").write_text("1")
    (dst / "b.txt").write_text("2")

    stats = scan_mirror_diff(str(src), str(dst))
    assert stats.files_to_remove == []
    assert stats.dirs_to_remove == []
    assert stats.total_destination_files == 2


def test_scan_extra_files(src, dst):
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    (dst / "extra1.txt").write_text("x")
    (dst / "extra2.txt").write_text("y")

    stats = scan_mirror_diff(str(src), str(dst))
    assert set(stats.files_to_remove) == {"extra1.txt", "extra2.txt"}
    assert stats.total_destination_files == 3


def test_scan_extra_dirs(src, dst):
    (src / "keep_dir").mkdir()
    (src / "keep_dir" / "f.txt").write_text("x")
    (dst / "keep_dir").mkdir()
    (dst / "keep_dir" / "f.txt").write_text("x")
    (dst / "extra_dir").mkdir()
    (dst / "extra_dir" / "y.txt").write_text("y")

    stats = scan_mirror_diff(str(src), str(dst))

    files = {str(Path(p)) for p in stats.files_to_remove}
    dirs = {str(Path(p)) for p in stats.dirs_to_remove}

    assert "extra_dir" in dirs
    assert str(Path("extra_dir") / "y.txt") in files


def test_scan_skips_special(src, dst):
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    # Служебные папки в destination не трогаем.
    (dst / "!CCRun").mkdir()
    (dst / "!CCRun" / "hashes.json").write_text("{}")
    (dst / "!Backup_old").mkdir()

    stats = scan_mirror_diff(str(src), str(dst))
    assert "!CCRun" not in stats.dirs_to_remove
    assert "!Backup_old" not in stats.dirs_to_remove
    assert "!CCRun/hashes.json" not in stats.files_to_remove


def test_scan_file_vs_dir_mismatch(src, dst):
    """В source файл, в destination — директория с тем же именем."""
    (src / "thing").write_text("file")
    (dst / "thing").mkdir()
    (dst / "thing" / "inner.txt").write_text("x")

    stats = scan_mirror_diff(str(src), str(dst))
    assert "thing" in stats.dirs_to_remove


# --- CopyService с mirror ---

def _run_with_mirror(
    src, dst, *, create_backup=True, mirror=True, timeout=10.0,
):
    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    results = []
    errors = []

    started = svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=create_backup,
        mirror_mode=mirror,
        hash_cache_enabled=False,   # для простоты тестов
        on_progress=lambda p: None,
        on_done=lambda r: (results.append(r), done.set()),
        on_error=errors.append,
    )
    assert started
    assert done.wait(timeout=timeout)
    assert errors == []
    return results[0]


def test_mirror_removes_extra_file(src, dst):
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    (dst / "extra.txt").write_text("remove me")

    r = _run_with_mirror(src, dst)

    assert r.mirror_removed_files == 1
    assert not (dst / "extra.txt").exists()
    assert (dst / "keep.txt").exists()

    # Blob "remove me" в pool — для отката.
    blobs = BlobStore(str(dst))
    sha = hashlib.sha256(b"remove me").hexdigest()
    p = blobs.get(sha)
    assert p is not None
    assert p.read_bytes() == b"remove me"


def test_mirror_removes_extra_dir(src, dst):
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    (dst / "old").mkdir()
    (dst / "old" / "f.txt").write_text("remove")

    r = _run_with_mirror(src, dst)

    assert not (dst / "old").exists()
    assert r.mirror_removed_files == 1     # old/f.txt
    assert r.mirror_removed_dirs == 1      # old


def test_mirror_ignores_create_backup_false(src, dst):
    """create_backup=False не отменяет mirror: states создаются
    принудительно, чтобы избежать безвозвратной потери."""
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    (dst / "extra.txt").write_text("x")

    r = _run_with_mirror(src, dst, create_backup=False)

    assert r.mirror_removed_files == 1
    assert not (dst / "extra.txt").exists()
    # State создан, потому что mirror.
    assert r.state_after_path is not None


def test_mirror_skips_special_dirs(src, dst):
    """!CCRun и !Backup_* в destination не трогаем."""
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    (dst / "!CCRun").mkdir()
    (dst / "!CCRun" / "hashes.json").write_text("{}")
    (dst / "!Backup_2026.01.01_00.00.00.000").mkdir()

    _run_with_mirror(src, dst)

    assert (dst / "!CCRun" / "hashes.json").exists()
    assert (dst / "!Backup_2026.01.01_00.00.00.000").exists()


def test_mirror_without_mirror_mode(src, dst):
    """Без mirror_mode файлы не удаляются."""
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    (dst / "extra.txt").write_text("x")

    r = _run_with_mirror(src, dst, mirror=False)

    assert r.mirror_removed_files == 0
    assert (dst / "extra.txt").exists()
