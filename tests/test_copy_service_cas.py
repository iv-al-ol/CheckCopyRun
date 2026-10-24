"""Тесты copy_service на CAS."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from services.cas.blob_store import BlobStore
from services.cas.current_pointer import CurrentPointer
from services.common.copy_constants import (
    CCRUN_DIR_NAME,
    STATES_DIR_NAME,
)
from services.copy.copy_service import CopyService


def _run_copy(
    src, dst,
    *,
    create_backup=True,
    mirror=False,
    hash_cache_enabled=False,
    timeout=10.0,
):
    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    results = []
    errors = []

    started = svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=create_backup,
        hash_cache_enabled=hash_cache_enabled,
        mirror_mode=mirror,
        on_progress=lambda _p: None,
        on_done=lambda r: (results.append(r), done.set()),
        on_error=errors.append,
    )
    assert started, "CopyService.start вернул False"
    assert done.wait(timeout=timeout), (
        f"Копирование не завершилось за {timeout} с"
    )
    assert errors == [], f"Ошибки: {errors}"
    assert len(results) == 1
    return results[0]


def test_copy_creates_states(src, dst):
    (src / "a.txt").write_text("hello")
    r = _run_copy(src, dst)

    states_dir = dst / CCRUN_DIR_NAME / STATES_DIR_NAME
    assert states_dir.is_dir()

    files = list(states_dir.glob("state_*.json"))
    # До copy destination был пуст — state_before не создаётся
    # (нечего откатывать). state_after создаётся, т.к. появился
    # файл.
    assert len(files) == 1
    assert r.state_after_path is not None
    assert r.state_before_path is None


def test_copy_populates_blobs(src, dst):
    (src / "a.txt").write_text("hello")

    _run_copy(src, dst)

    blobs = BlobStore(str(dst))
    count, size = blobs.stats()
    assert count == 1
    assert size == 5


def test_copy_updates_current(src, dst):
    (src / "a.txt").write_text("hello")
    r = _run_copy(src, dst)

    cur = CurrentPointer(str(dst)).load()
    assert cur is not None
    assert cur.last_action == "copy"
    assert cur.state.endswith(".json")

    assert r.state_after_path is not None
    assert Path(r.state_after_path).name == cur.state


def test_copy_no_changes_no_new_state(src, dst):
    (src / "a.txt").write_text("hello")
    _run_copy(src, dst)

    # Второй copy — без изменений.
    states_before = len(
        list((dst / CCRUN_DIR_NAME / STATES_DIR_NAME)
             .glob("state_*.json"))
    )
    r2 = _run_copy(src, dst)
    states_after = len(
        list((dst / CCRUN_DIR_NAME / STATES_DIR_NAME)
             .glob("state_*.json"))
    )
    assert states_before == states_after
    assert r2.state_before_path is None
    assert r2.state_after_path is None
    assert r2.skipped == 1


def test_copy_creates_before_after(src, dst):
    """Если были ручные правки — есть state_before + state_after."""
    (src / "a.txt").write_text("v1")
    (src / "b.txt").write_text("b1")
    _run_copy(src, dst)  # initial

    # Ручные правки.
    (dst / "a.txt").write_text("manual")

    # Изменение в source.
    (src / "a.txt").write_text("v2")

    r = _run_copy(src, dst)

    # В dst остался "manual", в src "v2" — есть что копировать.
    # state_before фиксирует "manual" (ручные правки),
    # state_after — "v2".
    assert r.state_before_path is not None
    assert r.state_after_path is not None

    # В blobs — обе версии a.txt.
    blobs = BlobStore(str(dst))
    assert blobs.stats()[0] >= 3   # v1, manual, v2 (b1 отдельно)
    # Точнее: v1=2, manual=6, v2=2, b1=2 → 4 уникальных.
    assert blobs.stats()[0] == 4


def test_copy_no_state_when_create_backup_false(src, dst):
    (src / "a.txt").write_text("hello")
    r = _run_copy(src, dst, create_backup=False)

    assert r.state_before_path is None
    assert r.state_after_path is None

    states_dir = dst / CCRUN_DIR_NAME / STATES_DIR_NAME
    assert not states_dir.exists() or not list(
        states_dir.glob("state_*.json")
    )


def test_mirror_requires_state(src, dst):
    """mirror + create_backup=False → states создаются принудительно."""
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    (dst / "extra.txt").write_text("x")

    r = _run_copy(
        src, dst, create_backup=False, mirror=True,
    )

    # Принудительно: state_after создан.
    assert r.state_after_path is not None
    # Файл удалён.
    assert not (dst / "extra.txt").exists()
    # Blob "x" в pool.
    blobs = BlobStore(str(dst))
    count, _ = blobs.stats()
    assert count >= 1


def test_mirror_preserves_removed_blobs(src, dst):
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    (dst / "extra.txt").write_text("extradata")

    _run_copy(src, dst, mirror=True)

    blobs = BlobStore(str(dst))
    # Оба файла (k и extradata) должны быть в pool.
    assert blobs.stats()[0] == 2

    # Содержимое extradata восстановимо.
    import hashlib
    sha = hashlib.sha256(b"extradata").hexdigest()
    p = blobs.get(sha)
    assert p is not None
    assert p.read_bytes() == b"extradata"


def test_state_file_format(src, dst):
    (src / "a.txt").write_text("hello")
    r = _run_copy(src, dst)

    assert r.state_after_path is not None
    data = json.loads(
        Path(r.state_after_path).read_text(encoding="utf-8")
    )
    assert data["version"] == 1
    assert data["kind"] == "auto"
    assert data["source"] == str(src)
    assert len(data["files"]) == 1
    assert data["files"][0]["path"] == "a.txt"
    assert data["summary"]["files_count"] == 1
    assert data["summary"]["total_size"] == 5
    assert data["summary"]["new_blobs_count"] == 1
    assert data["summary"]["new_blobs_bytes"] == 5


def test_ccrun_skipped_in_source(src, dst):
    (src / "!CCRun").mkdir()
    (src / "!CCRun" / "info.txt").write_text("meta")
    (src / "a.txt").write_text("hello")

    r = _run_copy(src, dst)
    assert r.copied == 1
    assert not (dst / "!CCRun" / "info.txt").exists()


def test_old_backup_dir_skipped_in_source(src, dst):
    old = src / "!Backup_2025.01.01_00.00.00.000"
    old.mkdir()
    (old / "old.txt").write_text("x")
    (src / "a.txt").write_text("hello")

    r = _run_copy(src, dst)
    assert r.copied == 1
    assert not (dst / old.name).exists()
