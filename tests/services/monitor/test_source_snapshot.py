"""Тесты stat-снимка источника и диффа."""

from __future__ import annotations

from services.monitor.source_snapshot import (
    build_snapshot,
    diff_snapshots,
    snapshot_from_dict,
    snapshot_to_dict,
)


def _write(path, text: str, mtime_ns: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime_ns is not None:
        path.touch()
        import os

        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, mtime_ns))


def test_build_snapshot_missing_source():
    assert build_snapshot("") is None
    assert build_snapshot("C:/definitely/not/exists") is None


def test_build_snapshot_counts_files(tmp_path):
    _write(tmp_path / "a.txt", "aaa")
    _write(tmp_path / "sub" / "b.txt", "bb")

    snap = build_snapshot(str(tmp_path))

    assert snap is not None
    assert snap["total_files"] == 2
    assert snap["truncated"] is False
    assert set(snap["files"]) == {"a.txt", "sub/b.txt"}
    assert snap["total_bytes"] == 5


def test_build_snapshot_skips_ccrun_dir(tmp_path):
    _write(tmp_path / "a.txt", "aaa")
    _write(tmp_path / "!CCRun" / "message.txt", "hello")

    snap = build_snapshot(str(tmp_path))

    assert snap is not None
    assert snap["total_files"] == 1
    assert "!CCRun/message.txt" not in snap["files"]


def test_build_snapshot_truncates_large_tree(tmp_path):
    for i in range(5):
        _write(tmp_path / f"f{i}.txt", "x")

    snap = build_snapshot(str(tmp_path), max_files=2)

    assert snap is not None
    assert snap["truncated"] is True
    assert snap["files"] == {}
    assert snap["total_files"] == 3


def test_diff_no_changes(tmp_path):
    _write(tmp_path / "a.txt", "aaa")
    first = build_snapshot(str(tmp_path))
    second = build_snapshot(str(tmp_path))

    diff = diff_snapshots(first, second)

    assert diff.has_changes is False
    assert diff.added == diff.modified == diff.removed == 0


def test_diff_detects_added_modified_removed(tmp_path):
    _write(tmp_path / "keep.txt", "keep")
    _write(tmp_path / "change.txt", "old", mtime_ns=1_000_000_000)
    _write(tmp_path / "gone.txt", "gone")
    before = build_snapshot(str(tmp_path))

    _write(tmp_path / "change.txt", "old but touched", mtime_ns=2_000_000_000)
    (tmp_path / "gone.txt").unlink()
    _write(tmp_path / "new.txt", "new")

    after = build_snapshot(str(tmp_path))
    diff = diff_snapshots(before, after)

    assert diff.added == 1
    assert diff.modified == 1
    assert diff.removed == 1
    assert diff.total_changed == 3


def test_diff_with_none_is_empty(tmp_path):
    _write(tmp_path / "a.txt", "aaa")
    snap = build_snapshot(str(tmp_path))

    assert diff_snapshots(None, snap).has_changes is False
    assert diff_snapshots(snap, None).has_changes is False


def test_diff_aggregate_mode(tmp_path):
    _write(tmp_path / "a.txt", "aaa")
    snap = build_snapshot(str(tmp_path))
    truncated_old = dict(snap, truncated=True, files={})
    truncated_new = dict(
        snap, truncated=True, files={}, total_files=99,
    )

    diff = diff_snapshots(truncated_old, truncated_new)

    assert diff.has_changes is True
    assert diff.modified == 99


def test_snapshot_roundtrip():
    original = {
        "source": "C:/src",
        "files": {"a.txt": [3, 111]},
        "total_files": 1,
        "total_bytes": 3,
        "max_mtime_ns": 111,
        "truncated": False,
    }

    restored = snapshot_from_dict(snapshot_to_dict(original))

    assert restored == original


def test_snapshot_from_dict_rejects_garbage():
    assert snapshot_from_dict(None) is None
    assert snapshot_from_dict("nope") is None

    restored = snapshot_from_dict(
        {"files": {"bad": "oops", "ok": [1, 2]}},
    )
    assert restored is not None
    assert restored["files"] == {"ok": [1, 2]}
