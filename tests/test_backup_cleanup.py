"""Тесты политики очистки состояний + GC blob-ов."""

from __future__ import annotations

import hashlib
import time

from services.backup_cleanup import (
    CleanupPolicy,
    cleanup_states,
)
from services.blob_store import BlobStore
from services.copy_constants import STATE_KIND_AUTO
from services.current_pointer import CurrentPointer
from services.state_store import (
    StateData,
    StateFile,
    StateStore,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_state(
    dst, tmp_path, files: dict[str, bytes],
) -> str:
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
        kind=STATE_KIND_AUTO,
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


# --- Политика ---

def test_policy_inactive_by_default():
    p = CleanupPolicy()
    assert p.is_active is False


def test_policy_active_keep_last():
    p = CleanupPolicy(keep_last_enabled=True)
    assert p.is_active is True


def test_policy_active_delete_older():
    p = CleanupPolicy(delete_older_enabled=True)
    assert p.is_active is True


# --- Очистка: базовые случаи ---

def test_cleanup_inactive_noop(tmp_path, dst):
    _make_state(dst, tmp_path, {"a.txt": b"a"})
    result = cleanup_states(str(dst), CleanupPolicy())

    assert result.total_found == 0
    assert result.deleted_count == 0

    # Состояние на месте.
    assert len(StateStore(str(dst)).list()) == 1


def test_cleanup_empty_destination(tmp_path, dst):
    policy = CleanupPolicy(keep_last_enabled=True, keep_last_n=3)
    result = cleanup_states(str(dst), policy)
    assert result.total_found == 0
    assert result.deleted_count == 0


def test_cleanup_keep_last(tmp_path, dst):
    """5 состояний, keep_last=3 → оставить 3 самых свежих + текущее."""
    names = []
    for i in range(5):
        name = _make_state(
            dst, tmp_path, {f"f{i}.txt": f"v{i}".encode()},
        )
        names.append(name)
        time.sleep(0.005)

    # Текущее — самое свежее.
    CurrentPointer(str(dst)).save_copy(names[-1])

    policy = CleanupPolicy(
        keep_last_enabled=True, keep_last_n=3,
    )
    result = cleanup_states(str(dst), policy)

    assert result.total_found == 5
    assert result.deleted_count == 2

    remaining = StateStore(str(dst)).list()
    assert len(remaining) == 3
    remaining_names = {s.path.name for s in remaining}
    # Оставлены 3 самых свежих (names[2:]).
    assert remaining_names == set(names[2:])


def test_cleanup_keep_last_protects_current(tmp_path, dst):
    """Если current не попадает в keep_last_n — он всё равно
    защищён от удаления."""
    names = []
    for i in range(5):
        name = _make_state(
            dst, tmp_path, {f"f{i}.txt": f"v{i}".encode()},
        )
        names.append(name)
        time.sleep(0.005)

    # Текущее — самое старое (names[0]).
    CurrentPointer(str(dst)).save_copy(names[0])

    policy = CleanupPolicy(
        keep_last_enabled=True, keep_last_n=2,
    )
    result = cleanup_states(str(dst), policy)

    remaining = StateStore(str(dst)).list()
    remaining_names = {s.path.name for s in remaining}

    # Должны остаться: 2 самых свежих + текущий (names[0]).
    assert names[0] in remaining_names, "current должен сохраниться"
    assert names[3] in remaining_names
    assert names[4] in remaining_names
    assert len(remaining_names) == 3


def test_cleanup_delete_older(tmp_path, dst):
    """delete_older: удалить состояния старше X дней."""
    # Свежее состояние.
    name_new = _make_state(
        dst, tmp_path, {"a.txt": b"a"},
    )
    time.sleep(0.005)

    # Искусственно портим timestamp в имени старого state —
    # проще создать state и переименовать его в старое имя.
    store = StateStore(str(dst))
    name_old = _make_state(dst, tmp_path, {"b.txt": b"b"})
    # Переименуем в 2020 год.
    old_path = store.root / name_old
    new_path = store.root / "state_2020.01.01_00.00.00.000.json"
    old_path.rename(new_path)

    CurrentPointer(str(dst)).save_copy(name_new)

    policy = CleanupPolicy(
        delete_older_enabled=True, delete_older_days=30,
    )
    result = cleanup_states(str(dst), policy)

    remaining = StateStore(str(dst)).list()
    remaining_names = {s.path.name for s in remaining}
    assert new_path.name not in remaining_names
    assert name_new in remaining_names


def test_cleanup_gc_blobs(tmp_path, dst):
    """После удаления состояний blob-ы, на которые больше никто
    не ссылается, удаляются."""
    # state1 = {a.txt: old_a}
    name1 = _make_state(dst, tmp_path, {"a.txt": b"old_a"})
    time.sleep(0.005)
    # state2 = {a.txt: new_a}
    name2 = _make_state(dst, tmp_path, {"a.txt": b"new_a"})
    time.sleep(0.005)
    # state3 = {a.txt: latest_a}
    name3 = _make_state(dst, tmp_path, {"a.txt": b"latest_a"})

    CurrentPointer(str(dst)).save_copy(name3)

    blobs = BlobStore(str(dst))
    assert blobs.stats()[0] == 3

    policy = CleanupPolicy(
        keep_last_enabled=True, keep_last_n=1,
    )
    result = cleanup_states(str(dst), policy)

    # Остались name3 (текущий, самый свежий).
    remaining = StateStore(str(dst)).list()
    assert len(remaining) == 1
    assert remaining[0].path.name == name3

    # Blob-ы old_a и new_a удалены, latest_a — остался.
    assert blobs.stats()[0] == 1
    sha_latest = _sha(b"latest_a")
    assert blobs.get(sha_latest) is not None

    sha_old = _sha(b"old_a")
    assert blobs.get(sha_old) is None


def test_cleanup_keep_last_n_zero(tmp_path, dst):
    """keep_last_n=0: оставить только текущее."""
    names = []
    for i in range(3):
        name = _make_state(
            dst, tmp_path, {f"f{i}.txt": f"v{i}".encode()},
        )
        names.append(name)
        time.sleep(0.005)

    CurrentPointer(str(dst)).save_copy(names[-1])

    policy = CleanupPolicy(
        keep_last_enabled=True, keep_last_n=0,
    )
    result = cleanup_states(str(dst), policy)

    remaining = StateStore(str(dst)).list()
    assert len(remaining) == 1
    assert remaining[0].path.name == names[-1]


def test_cleanup_both_policies(tmp_path, dst):
    """Если включены оба правила — удаление по любому."""
    # Старое состояние.
    store = StateStore(str(dst))
    name_old = _make_state(dst, tmp_path, {"old.txt": b"o"})
    old_path = store.root / name_old
    old_path.rename(
        store.root / "state_2020.01.01_00.00.00.000.json"
    )

    # Свежие.
    names = []
    for i in range(3):
        name = _make_state(
            dst, tmp_path, {f"f{i}.txt": f"v{i}".encode()},
        )
        names.append(name)
        time.sleep(0.005)

    CurrentPointer(str(dst)).save_copy(names[-1])

    policy = CleanupPolicy(
        keep_last_enabled=True, keep_last_n=1,
        delete_older_enabled=True, delete_older_days=30,
    )
    cleanup_states(str(dst), policy)

    remaining = StateStore(str(dst)).list()
    remaining_names = {s.path.name for s in remaining}

    # Остался только текущий.
    assert remaining_names == {names[-1]}
