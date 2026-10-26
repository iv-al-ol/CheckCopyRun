"""Тесты персистентной базы мониторинга."""

from __future__ import annotations

import json

from services.monitor.monitor_state import (
    MonitorEntry,
    MonitorStore,
)


def _entry(profile_id: str = "abc123", source: str = "C:/src"):
    return MonitorEntry(
        profile_id=profile_id,
        source=source,
        snapshot={
            "source": source,
            "files": {"a.txt": [1, 2]},
            "total_files": 1,
            "total_bytes": 1,
            "max_mtime_ns": 2,
            "truncated": False,
        },
        message_sha256="deadbeef",
    )


def test_load_when_no_base(tmp_path):
    store = MonitorStore(tmp_path)
    assert store.load("abc123") is None


def test_save_and_load_roundtrip(tmp_path):
    store = MonitorStore(tmp_path)
    entry = _entry()

    assert store.save(entry) is True
    loaded = store.load("abc123")

    assert loaded is not None
    assert loaded.source == "C:/src"
    assert loaded.message_sha256 == "deadbeef"
    assert loaded.snapshot is not None
    assert loaded.snapshot["files"] == {"a.txt": [1, 2]}


def test_save_is_atomic_no_tmp_left(tmp_path):
    store = MonitorStore(tmp_path)
    store.save(_entry())

    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_unsafe_profile_id_rejected(tmp_path):
    store = MonitorStore(tmp_path)
    assert store.path_for("../evil") is None
    assert store.path_for("") is None
    assert store.save(_entry(profile_id="../evil")) is False


def test_load_corrupted_json(tmp_path):
    store = MonitorStore(tmp_path)
    path = tmp_path / "abc123.json"
    path.write_text("{not json", encoding="utf-8")

    assert store.load("abc123") is None


def test_load_non_object_json(tmp_path):
    store = MonitorStore(tmp_path)
    (tmp_path / "abc123.json").write_text(
        json.dumps([1, 2, 3]), encoding="utf-8",
    )

    assert store.load("abc123") is None


def test_clear_removes_entry(tmp_path):
    store = MonitorStore(tmp_path)
    store.save(_entry())
    store.clear("abc123")

    assert store.load("abc123") is None


def test_clear_missing_entry_is_noop(tmp_path):
    store = MonitorStore(tmp_path)
    store.clear("nope")


def test_prune_removes_unknown_profiles(tmp_path):
    store = MonitorStore(tmp_path)
    store.save(_entry("keep1"))
    store.save(_entry("keep2"))
    store.save(_entry("drop"))

    removed = store.prune({"keep1", "keep2"})

    assert removed == 1
    assert store.load("drop") is None
    assert store.load("keep1") is not None


def test_prune_on_missing_dir(tmp_path):
    store = MonitorStore(tmp_path / "absent")
    assert store.prune({"x"}) == 0


def test_entry_ignores_garbage_snapshot(tmp_path):
    store = MonitorStore(tmp_path)
    (tmp_path / "abc123.json").write_text(
        json.dumps({
            "profile_id": "abc123",
            "source": "C:/src",
            "snapshot": "garbage",
            "message_sha256": "",
        }),
        encoding="utf-8",
    )

    loaded = store.load("abc123")

    assert loaded is not None
    assert loaded.snapshot is None
