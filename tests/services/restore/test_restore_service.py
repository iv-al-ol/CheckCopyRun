"""Тесты CAS-restore."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from services.cas.current_pointer import CurrentPointer
from services.cas.state_store import StateStore
from services.common.copy_constants import STATE_KIND_RESTORE_POINT
from services.restore.restore_service import (
    RestoreProgress,
    RestoreResult,
    format_restore_status,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_progress_percent():
    assert RestoreProgress(0, 0).percent == 100
    assert RestoreProgress(5, 10).percent == 50
    assert RestoreProgress(10, 10).percent == 100


def test_format_success():
    r = RestoreResult(
        total_actions=4,
        restored=2, deleted_files=1, created_dirs=1,
    )
    assert "восстановлено 2" in format_restore_status(r)
    assert "удалено файлов 1" in format_restore_status(r)


def test_format_already_there():
    r = RestoreResult(total_actions=0, errors=0)
    assert format_restore_status(r) == "Уже в этом состоянии"


def test_format_cancel_no_attempt():
    r = RestoreResult(cancelled=True)
    assert "отменено" in format_restore_status(r)


def test_format_cancel_rolled_back():
    r = RestoreResult(
        cancelled=True,
        rollback_attempted=True,
        rolled_back=True,
    )
    assert "изменения отменены" in format_restore_status(r)


def test_format_cancel_partial():
    r = RestoreResult(
        cancelled=True,
        rollback_attempted=True,
        rolled_back=False,
        rollback_errors=2,
    )
    txt = format_restore_status(r)
    assert "откат неполный" in txt
    assert "2" in txt


# --- Базовые restore ---

def test_restore_to_old_version(
    src, dst, run_copy, run_restore,
):
    (src / "a.txt").write_text("v1")
    (src / "b.txt").write_text("b1")
    r1 = run_copy(src, dst)

    (src / "a.txt").write_text("v2")
    run_copy(src, dst)

    old_state = Path(r1.state_after_path).name
    r = run_restore(old_state, dst)

    assert r.restored >= 1
    assert r.errors == 0
    assert (dst / "a.txt").read_text() == "v1"
    assert (dst / "b.txt").read_text() == "b1"


def test_restore_updates_current(
    src, dst, run_copy, run_restore,
):
    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)
    (src / "a.txt").write_text("v2")
    run_copy(src, dst)

    old_name = Path(r1.state_after_path).name
    run_restore(old_name, dst)

    cur = CurrentPointer(str(dst)).load()
    assert cur is not None
    assert cur.last_action == "restore"
    assert cur.state == old_name
    assert cur.restored_from == old_name


def test_restore_already_there(
    src, dst, run_copy, run_restore,
):
    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)

    r = run_restore(Path(r1.state_after_path).name, dst)
    assert r.total_actions == 0
    assert r.restored == 0
    assert r.errors == 0


def test_restore_missing_state(dst):
    from services.restore.restore_service import RestoreService
    svc = RestoreService(scheduler=lambda fn: fn())
    errors = []
    started = svc.start(
        backup_state_ref="state_nonexistent.json",
        destination=str(dst),
        on_progress=lambda _p: None,
        on_done=lambda _r: None,
        on_error=errors.append,
    )
    assert started is True
    time.sleep(0.5)
    assert errors, "Ожидалась ошибка чтения состояния"


def test_restore_deletes_extra_files(
    src, dst, run_copy, run_restore,
):
    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)

    (dst / "extra.txt").write_text("to-delete")

    run_restore(Path(r1.state_after_path).name, dst)
    assert not (dst / "extra.txt").exists()


def test_restore_after_mirror_restores_removed(
    src, dst, run_copy, run_restore,
):
    """Mirror удалил extra, restore к state_before возвращает."""
    (src / "keep.txt").write_text("k")
    (dst / "keep.txt").write_text("k")
    (dst / "extra.txt").write_text("extradata")

    r_copy = run_copy(src, dst, mirror=True)
    assert not (dst / "extra.txt").exists()
    assert r_copy.state_before_path is not None

    r = run_restore(Path(r_copy.state_before_path).name, dst)
    assert (dst / "extra.txt").read_text() == "extradata"
    assert (dst / "keep.txt").read_text() == "k"
    assert r.errors == 0


# --- Вариант A: переиспользование restore_point ---

def test_restore_reuses_current_state(
    src, dst, run_copy, run_restore,
):
    """Если destination совпадает с current.state — новый
    restore_point не создаётся."""
    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)
    (src / "a.txt").write_text("v2")
    run_copy(src, dst)

    store = StateStore(str(dst))
    states_before = len(store.list())

    r = run_restore(Path(r1.state_after_path).name, dst)

    states_after = len(store.list())
    assert states_after == states_before, (
        "Лишний restore_point создан, хотя destination "
        "совпадает с current.state"
    )
    assert r.reused_restore_point is True
    assert r.restore_point_path is not None
    assert Path(r.restore_point_path).is_file()
    assert (dst / "a.txt").read_text() == "v1"


def test_restore_creates_new_when_manual_edit(
    src, dst, run_copy, run_restore,
):
    """Если destination был изменён вручную — создаётся
    новая точка возврата."""
    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)
    (src / "a.txt").write_text("v2")
    run_copy(src, dst)

    # Ручное изменение — destination ≠ current.state.
    (dst / "a.txt").write_text("manual")

    store = StateStore(str(dst))
    states_before = len(store.list())

    r = run_restore(Path(r1.state_after_path).name, dst)

    states_after = len(store.list())
    assert states_after == states_before + 1, (
        "Ожидалась новая точка возврата для ручной правки"
    )
    assert r.reused_restore_point is False
    assert r.restore_point_path is not None

    data = json.loads(
        Path(r.restore_point_path).read_text(encoding="utf-8")
    )
    assert data["kind"] == STATE_KIND_RESTORE_POINT


def test_restore_cycle_no_extra_points(
    src, dst, run_copy, run_restore,
):
    """Цикл A → B → A → B без ручных правок не создаёт
    новых state-файлов."""
    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)
    (src / "a.txt").write_text("v2")
    r2 = run_copy(src, dst)

    store = StateStore(str(dst))
    states_initial = len(store.list())

    a_name = Path(r1.state_after_path).name
    b_name = Path(r2.state_after_path).name

    # A → B
    run_restore(a_name, dst)
    assert (dst / "a.txt").read_text() == "v1"
    # B → A
    run_restore(b_name, dst)
    assert (dst / "a.txt").read_text() == "v2"
    # A → B
    run_restore(a_name, dst)
    assert (dst / "a.txt").read_text() == "v1"
    # B → A
    run_restore(b_name, dst)
    assert (dst / "a.txt").read_text() == "v2"

    states_after = len(store.list())
    assert states_after == states_initial, (
        f"Цикл создал {states_after - states_initial} "
        f"лишних state-файлов"
    )


def test_restore_first_time_creates_restore_point(
    src, dst, run_copy, run_restore,
):
    """Первый restore после ручных правок создаёт точку
    возврата — как и раньше."""
    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)

    # Destination != current.state (нет current вообще,
    # т.к. current установлен на state_after копии v1).
    # Принудительно ломаем: правим файл.
    (dst / "a.txt").write_text("manual")

    store = StateStore(str(dst))
    states_before = len(store.list())

    r = run_restore(Path(r1.state_after_path).name, dst)

    assert len(store.list()) == states_before + 1
    assert r.reused_restore_point is False


# --- Отмена с откатом ---

def test_cancel_restore_rolls_back_created_point(
    src, dst, run_copy, run_restore,
):
    """Отмена restore с Созданной точкой возврата — откат
    через неё."""
    for i in range(10):
        (src / f"f{i}.txt").write_text("v1")
    r1 = run_copy(src, dst)

    # Ручное изменение — следующая restore создаст restore_point.
    (dst / "extra.txt").write_text("manual")

    for i in range(10):
        (src / f"f{i}.txt").write_text("v2")
    run_copy(src, dst)

    # Возвращаемся к v1, отменяем на середине.
    old_name = Path(r1.state_after_path).name
    r = run_restore(old_name, dst, cancel_after=3)

    assert r.cancelled is True
    assert r.rollback_attempted is True
    assert r.rolled_back is True

    # Состояние как до restore — v2 + extra.txt.
    for i in range(10):
        assert (dst / f"f{i}.txt").read_text() == "v2"
    assert (dst / "extra.txt").exists()


def test_cancel_restore_rolls_back_reused_point(
    src, dst, run_copy, run_restore,
):
    """Отмена restore с переиспользованной точкой возврата
    тоже откатывается."""
    for i in range(10):
        (src / f"f{i}.txt").write_text("v1")
    r1 = run_copy(src, dst)

    for i in range(10):
        (src / f"f{i}.txt").write_text("v2")
    run_copy(src, dst)

    # destination = v2 = current.state → reuse.
    old_name = Path(r1.state_after_path).name
    r = run_restore(old_name, dst, cancel_after=3)

    assert r.cancelled is True
    assert r.rollback_attempted is True
    assert r.rolled_back is True
    assert r.reused_restore_point is True

    # Состояние как до restore — v2.
    for i in range(10):
        assert (dst / f"f{i}.txt").read_text() == "v2"

# --- Дедупликация restore_point ---

def test_restore_point_reuses_current(
    src, dst, run_copy, run_restore,
):
    """Если current.state совпадает с destination —
    restore_point переиспользует его (уже было в варианте A)."""
    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)
    (src / "a.txt").write_text("v2")
    run_copy(src, dst)

    from services.cas.state_store import StateStore
    states_before = len(StateStore(str(dst)).list())

    r = run_restore(Path(r1.state_after_path).name, dst)

    assert r.reused_restore_point is True
    assert len(StateStore(str(dst)).list()) == states_before


def test_restore_point_reuses_when_current_broken(
    src, dst, run_copy, run_restore,
):
    """Если current указывает не туда, но среди states есть
    идентичный — переиспользуем его."""
    from services.cas.current_pointer import (
        CurrentData,
        CurrentPointer,
    )
    from services.cas.state_store import StateStore

    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)  # A

    (src / "a.txt").write_text("v2")
    run_copy(src, dst)  # B (current=B)

    # Ломаем current.
    CurrentPointer(str(dst)).save(CurrentData(
        state="state_broken.json",
        last_action="copy",
        last_action_at="",
    ))

    states_before = len(StateStore(str(dst)).list())

    # Restore к A. Destination=B (совпадает с state B в states).
    # current сломан, но B есть в states — переиспользуем.
    r = run_restore(Path(r1.state_after_path).name, dst)

    assert r.reused_restore_point is True
    assert len(StateStore(str(dst)).list()) == states_before


def test_restore_point_creates_when_manual_edit(
    src, dst, run_copy, run_restore,
):
    """Если destination был изменён вручную — создаётся
    новая точка возврата (нельзя переиспользовать)."""
    from services.cas.state_store import StateStore

    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)  # A

    (src / "a.txt").write_text("v2")
    run_copy(src, dst)  # B

    # Ручное изменение — destination не совпадает ни с одним
    # state в states.
    (dst / "a.txt").write_text("manual")

    states_before = len(StateStore(str(dst)).list())

    r = run_restore(Path(r1.state_after_path).name, dst)

    assert r.reused_restore_point is False
    assert len(StateStore(str(dst)).list()) == states_before + 1


def test_should_skip_mixed_separators():
    """_should_skip не различает / и \\ в путях."""
    from services.cas.state_store import (
        StateData,
        StateFile,
    )
    from services.restore.restore_service import _RestoreWorker

    a = StateData(
        files=[
            StateFile(
                path="sub/a.txt",
                sha256="aa" * 32,
                size=1, mtime="",
            ),
        ],
        empty_dirs=["empty/dir"],
    )
    b = StateData(
        files=[
            StateFile(
                path="sub\\a.txt",
                sha256="aa" * 32,
                size=1, mtime="",
            ),
        ],
        empty_dirs=["empty\\dir"],
    )

    assert _RestoreWorker._should_skip(a, b) is True
