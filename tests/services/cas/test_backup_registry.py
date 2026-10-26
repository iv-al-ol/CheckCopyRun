"""Тесты реестра состояний."""

from __future__ import annotations

import hashlib

from services.cas.backup_registry import (
    compute_ui_info,
    delete_state,
    get_current,
    list_states,
)
from services.cas.blob_store import BlobStore
from services.cas.current_pointer import CurrentPointer
from services.cas.state_store import (
    StateData,
    StateFile,
    StateStore,
)
from services.common.copy_constants import (
    STATE_KIND_AUTO,
    STATE_KIND_RESTORE_POINT,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_state(
    dst, tmp_path, files: dict[str, bytes],
    kind: str = STATE_KIND_AUTO,
) -> str:
    """Создаёт state и кидает файлы в blob-pool.

    Возвращает имя state-файла.
    """
    store = StateStore(str(dst))
    blobs = BlobStore(str(dst))

    state_files = []
    for rel, data in files.items():
        src = tmp_path / "src.bin"
        src.write_bytes(data)
        sha = _sha(data)
        blobs.put(str(src), sha)
        state_files.append(StateFile(
            path=rel, sha256=sha,
            size=len(data), mtime="",
        ))

    data_obj = StateData(
        version=1,
        created_at="2026-01-01T00:00:00.000",
        kind=kind,
        source="src",
        files=state_files,
        empty_dirs=[],
        summary={
            "files_count": len(state_files),
            "empty_dirs_count": 0,
            "total_size": sum(f.size for f in state_files),
            "new_blobs_count": len(state_files),
            "new_blobs_bytes": sum(f.size for f in state_files),
        },
    )
    path = store.create(data_obj)
    return path.name


# --- list_states ---

def test_list_empty(tmp_path, dst):
    assert list_states(str(dst)) == []
    assert list_states("") == []


def test_list_single(tmp_path, dst):
    _make_state(dst, tmp_path, {"a.txt": b"a"})
    states = list_states(str(dst))
    assert len(states) == 1
    assert states[0].files_count == 1


def test_list_sorted_desc(tmp_path, dst):
    import time
    _make_state(dst, tmp_path, {"a.txt": b"a"})
    time.sleep(0.005)
    _make_state(dst, tmp_path, {"b.txt": b"b"})

    states = list_states(str(dst))
    assert len(states) == 2
    # Свежие сначала.
    assert states[0].timestamp >= states[1].timestamp


# --- get_current ---

def test_get_current_none(tmp_path, dst):
    assert get_current(str(dst)) is None


def test_get_current_set(tmp_path, dst):
    name = _make_state(dst, tmp_path, {"a.txt": b"a"})
    cp = CurrentPointer(str(dst))
    cp.save_copy(name)

    cur = get_current(str(dst))
    assert cur is not None
    assert cur.state == name


# --- compute_ui_info ---

def test_ui_info_current(tmp_path, dst):
    name = _make_state(dst, tmp_path, {"a.txt": b"a"})
    cp = CurrentPointer(str(dst))
    cp.save_copy(name)

    info = list_states(str(dst))[0]
    cur = get_current(str(dst))
    ui = compute_ui_info(info, cur)

    assert ui.is_current is True
    assert ui.is_restore_point is False


def test_ui_info_restore_point(tmp_path, dst):
    _make_state(
        dst, tmp_path, {"a.txt": b"a"},
        kind=STATE_KIND_RESTORE_POINT,
    )
    info = list_states(str(dst))[0]
    ui = compute_ui_info(info, None)

    assert ui.is_current is False
    assert ui.is_restore_point is True


def test_ui_info_plain(tmp_path, dst):
    _make_state(dst, tmp_path, {"a.txt": b"a"})
    info = list_states(str(dst))[0]
    ui = compute_ui_info(info, None)

    assert ui.is_current is False
    assert ui.is_restore_point is False


# --- delete_state ---

def test_delete_ok(tmp_path, dst):
    import time
    name1 = _make_state(dst, tmp_path, {"a.txt": b"a"})
    time.sleep(0.005)
    name2 = _make_state(dst, tmp_path, {"b.txt": b"b"})
    # Делаем name2 текущим.
    CurrentPointer(str(dst)).save_copy(name2)

    ok, err = delete_state(
        str(dst), dst / "!CCRun" / "states" / name1,
    )
    assert ok is True
    assert err == ""

    remaining = list_states(str(dst))
    assert len(remaining) == 1
    assert remaining[0].path.name == name2


def test_delete_current_forbidden(tmp_path, dst):
    name = _make_state(dst, tmp_path, {"a.txt": b"a"})
    CurrentPointer(str(dst)).save_copy(name)

    ok, err = delete_state(str(dst), name)
    assert ok is False
    assert "текущее" in err.lower()

    # State на месте.
    assert len(list_states(str(dst))) == 1


def test_delete_missing(tmp_path, dst):
    ok, _err = delete_state(
        str(dst), "state_1999.01.01_00.00.00.000.json",
    )
    assert ok is False


def test_delete_no_destination():
    ok, err = delete_state("", "state_x.json")
    assert ok is False
    assert "папка назначения" in err.lower()
