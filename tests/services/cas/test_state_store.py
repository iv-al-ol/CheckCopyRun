"""Тесты хранилища состояний."""

from __future__ import annotations

import time

import pytest

from services.cas.state_store import (
    StateData,
    StateFile,
    StateStore,
    StateStoreError,
    now_iso,
)
from services.common.copy_constants import (
    STATE_KIND_AUTO,
    STATE_KIND_RESTORE_POINT,
    STATE_VERSION,
)


def _make_data(
    kind: str = STATE_KIND_AUTO,
    source: str = "src",
) -> StateData:
    return StateData(
        version=STATE_VERSION,
        created_at=now_iso(),
        kind=kind,
        source=source,
        files=[
            StateFile(
                path="a.txt",
                sha256="aa" * 32,
                size=10,
                mtime="2026-01-01T00:00:00.000",
            ),
        ],
        empty_dirs=["e1"],
        summary={
            "files_count": 1,
            "empty_dirs_count": 1,
            "total_size": 10,
            "new_blobs_count": 1,
            "new_blobs_bytes": 10,
        },
    )


def test_create_and_load(tmp_path):
    store = StateStore(str(tmp_path))
    path = store.create(_make_data())

    assert path.is_file()
    assert path.name.startswith("state_")
    assert path.suffix == ".json"

    loaded = store.load(path.name)
    assert loaded.kind == STATE_KIND_AUTO
    assert loaded.source == "src"
    assert len(loaded.files) == 1
    assert loaded.files[0].path == "a.txt"
    assert loaded.files[0].sha256 == "aa" * 32
    assert loaded.empty_dirs == ["e1"]
    assert loaded.summary["files_count"] == 1


def test_create_sets_created_at_when_empty(tmp_path):
    store = StateStore(str(tmp_path))
    data = _make_data()
    data.created_at = ""
    store.create(data)

    lst = store.list()
    assert lst[0].created_at


def test_list_sorted_desc(tmp_path):
    store = StateStore(str(tmp_path))
    store.create(_make_data())
    time.sleep(0.005)
    store.create(_make_data())

    lst = store.list()
    assert len(lst) == 2
    assert lst[0].timestamp >= lst[1].timestamp


def test_latest(tmp_path):
    store = StateStore(str(tmp_path))
    assert store.latest() is None
    store.create(_make_data())
    info = store.latest()
    assert info is not None
    assert info.files_count == 1
    assert info.empty_dirs_count == 1
    assert info.total_size == 10
    assert info.new_blobs_count == 1
    assert info.new_blobs_bytes == 10


def test_delete(tmp_path):
    store = StateStore(str(tmp_path))
    path = store.create(_make_data())

    assert store.delete(path.name) is True
    assert not path.exists()
    assert store.list() == []
    assert store.delete(path.name) is False


def test_get_by_name(tmp_path):
    store = StateStore(str(tmp_path))
    path = store.create(_make_data())

    info = store.get_by_name(path.stem)
    assert info is not None
    assert info.data.files[0].path == "a.txt"

    info2 = store.get_by_name(path.name)
    assert info2 is not None

    assert store.get_by_name("nonexistent") is None


def test_load_missing(tmp_path):
    store = StateStore(str(tmp_path))
    with pytest.raises(StateStoreError):
        store.load("state_2026.01.01_00.00.00.000.json")


def test_load_newer_version(tmp_path):
    store = StateStore(str(tmp_path))
    path = store.create(_make_data())

    # Вручную портим версию.
    content = path.read_text(encoding="utf-8")
    content = content.replace(
        f'"version": {STATE_VERSION}',
        '"version": 999',
    )
    path.write_text(content, encoding="utf-8")

    with pytest.raises(StateStoreError):
        store.load(path.name)


def test_two_in_same_ms_dont_collide(tmp_path):
    """При совпадении timestamp в пределах миллисекунды —
    имя получает числовой суффикс."""
    store = StateStore(str(tmp_path))
    p1 = store.create(_make_data())
    p2 = store.create(_make_data())
    assert p1 != p2
    assert p1.is_file() and p2.is_file()
    assert len(store.list()) == 2


def test_kind_restore_point(tmp_path):
    store = StateStore(str(tmp_path))
    store.create(_make_data(kind=STATE_KIND_RESTORE_POINT))
    info = store.latest()
    assert info is not None
    assert info.kind == STATE_KIND_RESTORE_POINT


def test_find_matching_mixed_separators(tmp_path):
    """find_matching не различает / и \\ в путях.

    Регресс-тест: раньше дедупликация ломалась, если
    state-файл отредактирован вручную или пришёл с другой ОС —
    создавался дубликат state_*.json.
    """
    store = StateStore(str(tmp_path))
    data_a = StateData(
        version=STATE_VERSION,
        created_at=now_iso(),
        kind=STATE_KIND_AUTO,
        source="",
        files=[
            StateFile(
                path="sub/a.txt",
                sha256="aa" * 32,
                size=1, mtime="",
            ),
        ],
        empty_dirs=["empty/dir"],
        summary={
            "files_count": 1,
            "empty_dirs_count": 1,
            "total_size": 1,
            "new_blobs_count": 0,
            "new_blobs_bytes": 0,
        },
    )
    name_a = store.create(data_a).name

    data_b = StateData(
        version=STATE_VERSION,
        created_at=now_iso(),
        kind=STATE_KIND_AUTO,
        source="",
        files=[
            StateFile(
                path="sub\\a.txt",
                sha256="aa" * 32,
                size=1, mtime="",
            ),
        ],
        empty_dirs=["empty\\dir"],
        summary={
            "files_count": 1,
            "empty_dirs_count": 1,
            "total_size": 1,
            "new_blobs_count": 0,
            "new_blobs_bytes": 0,
        },
    )

    found = store.find_matching(data_b)
    assert found == name_a
