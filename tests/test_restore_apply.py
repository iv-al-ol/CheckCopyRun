"""Тесты применения плана restore."""

from __future__ import annotations

import hashlib
import threading

from services.blob_store import BlobStore
from services.copy_constants import TMP_SUFFIX
from services.restore_apply import apply_plan
from services.restore_planner import build_plan
from services.state_store import StateData, StateFile


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _state(
    files: dict[str, bytes],
    empty_dirs: list[str] | None = None,
) -> StateData:
    return StateData(
        version=1,
        created_at="2026-01-01T00:00:00.000",
        kind="",
        source="",
        files=[
            StateFile(
                path=p,
                sha256=_sha(data),
                size=len(data),
                mtime="",
            )
            for p, data in files.items()
        ],
        empty_dirs=empty_dirs or [],
        summary={},
    )


def _put_blob(store: BlobStore, tmp_path, data: bytes) -> str:
    p = tmp_path / "src.bin"
    p.write_bytes(data)
    sha = _sha(data)
    store.put(str(p), sha)
    return sha


def test_apply_restore_file(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "a.txt").write_bytes(b"new")
    store = BlobStore(str(dst))
    _put_blob(store, tmp_path, b"old")

    target = _state({"a.txt": b"old"})
    current = _state({"a.txt": b"new"})
    plan = build_plan(target, current, store)

    result = apply_plan(plan, target, str(dst))
    assert result.restored == 1
    assert result.errors == 0
    assert (dst / "a.txt").read_bytes() == b"old"


def test_apply_delete_extra(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "a.txt").write_bytes(b"a")
    (dst / "b.txt").write_bytes(b"b")
    store = BlobStore(str(dst))

    target = _state({"a.txt": b"a"})
    current = _state({
        "a.txt": b"a",
        "b.txt": b"b",
    })
    plan = build_plan(target, current, store)
    result = apply_plan(plan, target, str(dst))

    assert result.deleted_files == 1
    assert not (dst / "b.txt").exists()
    assert (dst / "a.txt").exists()


def test_apply_create_empty_dirs(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    store = BlobStore(str(dst))

    target = _state({}, empty_dirs=["x", "y/z"])
    current = _state({})
    plan = build_plan(target, current, store)
    result = apply_plan(plan, target, str(dst))

    assert result.created_dirs == 2
    assert (dst / "x").is_dir()
    assert (dst / "y" / "z").is_dir()


def test_apply_cleanup_empty_dirs(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "empty1").mkdir()
    (dst / "empty2" / "empty3").mkdir(parents=True)
    store = BlobStore(str(dst))

    target = _state({})
    current = _state({})
    plan = build_plan(target, current, store)
    result = apply_plan(plan, target, str(dst))

    assert result.deleted_dirs >= 2
    assert not (dst / "empty1").exists()
    assert not (dst / "empty2").exists()


def test_apply_keeps_needed_dirs(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "keep").mkdir()
    store = BlobStore(str(dst))
    _put_blob(store, tmp_path, b"x")

    target = _state(
        {"keep/a.txt": b"x"},
        empty_dirs=["keep"],
    )
    current = _state({})
    plan = build_plan(target, current, store)
    result = apply_plan(plan, target, str(dst))

    assert (dst / "keep").is_dir()
    assert (dst / "keep" / "a.txt").read_bytes() == b"x"


def test_apply_cancel_between(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "a.txt").write_bytes(b"new_a")
    (dst / "b.txt").write_bytes(b"new_b")
    store = BlobStore(str(dst))
    _put_blob(store, tmp_path, b"old_a")
    _put_blob(store, tmp_path, b"old_b")

    target = _state({
        "a.txt": b"old_a",
        "b.txt": b"old_b",
    })
    current = _state({
        "a.txt": b"new_a",
        "b.txt": b"new_b",
    })
    plan = build_plan(target, current, store)

    cancel = threading.Event()

    def on_progress(processed, total):
        if processed >= 1:
            cancel.set()

    result = apply_plan(
        plan, target, str(dst),
        on_progress=on_progress,
        cancel_event=cancel,
    )
    assert result.cancelled is True


def test_apply_skips_service_paths(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    store = BlobStore(str(dst))

    target = _state({"!CCRun/evil.json": b"evil"})
    current = _state({})
    plan = build_plan(target, current, store)

    assert plan.to_restore == []
    result = apply_plan(plan, target, str(dst))
    assert not (dst / "!CCRun" / "evil.json").exists()


def test_apply_tmp_removed_on_error(tmp_path, monkeypatch):
    """Если копирование упало — .tmp не остаётся.

    Monkeypatch'им long_io.copy2 (не shutil) — именно через
    него работает restore_apply после перехода на long_io.
    """
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "a.txt").write_bytes(b"new")
    store = BlobStore(str(dst))
    _put_blob(store, tmp_path, b"old")

    target = _state({"a.txt": b"old"})
    current = _state({"a.txt": b"new"})
    plan = build_plan(target, current, store)

    import services.restore_apply as ra

    def boom(*args, **kwargs):
        raise OSError("simulated error")

    monkeypatch.setattr(ra.long_io, "copy2", boom)

    result = apply_plan(plan, target, str(dst))
    assert result.errors == 1

    leftovers = list(dst.glob(f"*{TMP_SUFFIX}"))
    assert leftovers == []

    assert (dst / "a.txt").read_bytes() == b"new"


def test_apply_missing_blob_no_error(tmp_path):
    """Файл без blob-а — не ошибка apply, а запись в
    plan.missing_blobs (её обрабатывает RestoreService)."""
    dst = tmp_path / "dst"
    dst.mkdir()
    store = BlobStore(str(dst))

    target = _state({"a.txt": b"never"})
    current = _state({})
    plan = build_plan(target, current, store)
    assert len(plan.missing_blobs) == 1

    result = apply_plan(plan, target, str(dst))
    assert result.errors == 0
    assert result.restored == 0
    assert not (dst / "a.txt").exists()
