"""Тесты планировщика restore."""

from __future__ import annotations

import hashlib

from services.cas.blob_store import BlobStore
from services.cas.state_store import StateData, StateFile
from services.restore.restore_planner import build_plan


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


def test_plan_same_target_current(tmp_path):
    store = BlobStore(str(tmp_path))
    _put_blob(store, tmp_path, b"a")
    target = _state({"a.txt": b"a"})
    current = _state({"a.txt": b"a"})

    plan = build_plan(target, current, store)
    assert plan.to_restore == []
    assert plan.to_delete_files == []
    assert plan.skipped_files == 1
    assert plan.total_actions == 0


def test_plan_restore_one(tmp_path):
    store = BlobStore(str(tmp_path))
    sha_old = _put_blob(store, tmp_path, b"old")
    target = _state({"a.txt": b"old"})
    current = _state({"a.txt": b"new"})

    plan = build_plan(target, current, store)
    assert len(plan.to_restore) == 1
    sf, blob = plan.to_restore[0]
    assert sf.path == "a.txt"
    assert sf.sha256 == sha_old
    assert blob.is_file()


def test_plan_delete_extra(tmp_path):
    store = BlobStore(str(tmp_path))
    target = _state({"a.txt": b"a"})
    current = _state({
        "a.txt": b"a",
        "b.txt": b"b",
    })

    plan = build_plan(target, current, store)
    assert plan.to_delete_files == ["b.txt"]


def test_plan_missing_blob(tmp_path):
    store = BlobStore(str(tmp_path))
    target = _state({"a.txt": b"missing"})
    current = _state({})

    plan = build_plan(target, current, store)
    assert len(plan.missing_blobs) == 1
    assert plan.missing_blobs[0].path == "a.txt"
    assert plan.to_restore == []


def test_plan_empty_dirs(tmp_path):
    store = BlobStore(str(tmp_path))
    target = _state({}, empty_dirs=["x", "y/z"])
    current = _state({})

    plan = build_plan(target, current, store)
    assert set(plan.create_dirs) == {"x", "y/z"}
    assert "y" in plan.needed_dirs
    assert "y/z" in plan.needed_dirs


def test_plan_needed_dirs_from_files(tmp_path):
    store = BlobStore(str(tmp_path))
    _put_blob(store, tmp_path, b"deep")
    target = _state({"a/b/c.txt": b"deep"})
    current = _state({})

    plan = build_plan(target, current, store)
    assert "a" in plan.needed_dirs
    assert "a/b" in plan.needed_dirs


def test_plan_to_delete_with_missing(tmp_path):
    """Одновременно: restore + delete + missing."""
    store = BlobStore(str(tmp_path))
    _put_blob(store, tmp_path, b"old")
    target = _state({
        "a.txt": b"old",
        "c.txt": b"never-in-blobs",
    })
    current = _state({
        "a.txt": b"new",
        "b.txt": b"remove",
    })

    plan = build_plan(target, current, store)
    assert len(plan.to_restore) == 1
    assert plan.to_delete_files == ["b.txt"]
    assert len(plan.missing_blobs) == 1
