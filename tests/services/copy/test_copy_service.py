"""Тесты сервиса копирования (CAS).

Покрытие:
  • копирование новых файлов;
  • пропуск идентичных;
  • замена;
  • создание state_after / state_before;
  • откат при отмене через CAS;
  • служебные папки !CCRun и !Backup_* в источнике;
  • тексты format_cancel_status;
  • тексты format_copy_status;
  • фазы прогресса: copy / save_scan / save_store;
  • валидация путей;
  • кэш SHA-256.
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

import pytest

from services.common.copy_constants import CCRUN_DIR_NAME
from services.copy.copy_service import (
    PHASE_COPY,
    PHASE_SAVE_SCAN,
    PHASE_SAVE_STORE,
    CopyProgress,
    CopyResult,
    CopyService,
    CopyValidationError,
    _validate,
    format_cancel_status,
    format_copy_status,
)

# --- Базовые типы ---

def test_result_defaults():
    r = CopyResult()
    assert r.total == 0
    assert r.copied == 0
    assert r.skipped == 0
    assert r.errors == 0
    assert r.backup_dir is None
    assert r.state_before_path is None
    assert r.state_after_path is None
    assert r.cancelled is False
    assert r.elapsed_sec == 0.0
    assert r.rollback_attempted is False
    assert r.rolled_back is False
    assert r.rollback_restored == 0
    assert r.rollback_deleted == 0
    assert r.rollback_errors == 0


def test_progress_percent():
    assert CopyProgress(
        processed=0, total=0, copied=0, skipped=0,
    ).percent == 100
    assert CopyProgress(
        processed=5, total=10, copied=0, skipped=0,
    ).percent == 50
    assert CopyProgress(
        processed=10, total=10, copied=0, skipped=0,
    ).percent == 100


def test_progress_phase_default():
    p = CopyProgress(0, 0, 0, 0)
    assert p.phase == PHASE_COPY


# --- Копирование: без замен ---

def test_empty_source(src, dst, run_copy):
    r = run_copy(src, dst, create_backup=True)
    assert r.total == 0
    assert r.copied == 0
    assert r.skipped == 0
    assert r.state_before_path is None
    assert r.state_after_path is None
    visible = [
        p for p in dst.iterdir()
        if p.name != CCRUN_DIR_NAME
    ]
    assert visible == []


def test_new_files_no_backup_flag(src, dst, run_copy):
    (src / "a.txt").write_text("1")
    (src / "b.txt").write_text("2")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 2
    assert r.copied == 2
    assert r.skipped == 0
    assert r.state_after_path is not None
    assert (dst / "a.txt").read_text() == "1"
    assert (dst / "b.txt").read_text() == "2"


def test_identical_files_skipped(src, dst, run_copy):
    (src / "a.txt").write_text("same")
    shutil.copy2(src / "a.txt", dst / "a.txt")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 1
    assert r.copied == 0
    assert r.skipped == 1


def test_nested_directories(src, dst, run_copy):
    (src / "sub1" / "sub2").mkdir(parents=True)
    (src / "sub1" / "sub2" / "deep.txt").write_text("deep")
    (src / "top.txt").write_text("top")

    r = run_copy(src, dst, create_backup=True)

    assert r.copied == 2
    assert (
        dst / "sub1" / "sub2" / "deep.txt"
    ).read_text() == "deep"
    assert (dst / "top.txt").read_text() == "top"


# --- Замена ---

def test_replaced_file_creates_states(src, dst, run_copy):
    (src / "a.txt").write_text("new")
    (dst / "a.txt").write_text("old")

    r = run_copy(src, dst, create_backup=True)

    assert r.copied == 1
    assert r.state_before_path is not None
    assert r.state_after_path is not None
    assert (dst / "a.txt").read_text() == "new"

    import hashlib
    old_sha = hashlib.sha256(b"old").hexdigest()
    data = json.loads(
        Path(r.state_before_path).read_text(encoding="utf-8")
    )
    files = {f["path"]: f for f in data["files"]}
    assert files["a.txt"]["sha256"] == old_sha


def test_replaced_file_without_backup(src, dst, run_copy):
    (src / "a.txt").write_text("new")
    (dst / "a.txt").write_text("old")

    r = run_copy(src, dst, create_backup=False)

    assert r.copied == 1
    assert r.state_before_path is None
    assert r.state_after_path is None
    assert (dst / "a.txt").read_text() == "new"


def test_state_file_name_format(src, dst, run_copy):
    import re

    (src / "a.txt").write_text("new")
    (dst / "a.txt").write_text("old")

    r = run_copy(src, dst, create_backup=True)
    assert r.state_after_path is not None

    name = Path(r.state_after_path).name
    pattern = (
        r"^state_\d{4}\.\d{2}\.\d{2}_"
        r"\d{2}\.\d{2}\.\d{2}\.\d{3}"
        r"(_\d+)?\.json$"
    )
    assert re.match(pattern, name), f"Формат: {name!r}"


# --- Служебные папки в source ---

def test_ccrun_skipped_in_source(src, dst, run_copy):
    (src / "!CCRun").mkdir()
    (src / "!CCRun" / "info.txt").write_text("meta")
    (src / "a.txt").write_text("hello")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 1
    assert not (dst / "!CCRun" / "info.txt").exists()


def test_backup_dirs_skipped_in_source(src, dst, run_copy):
    (src / "!Backup_2025.01.01_00.00.00.000").mkdir()
    (
        src
        / "!Backup_2025.01.01_00.00.00.000"
        / "old.txt"
    ).write_text("x")
    (src / "a.txt").write_text("hello")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 1
    assert not (
        dst / "!Backup_2025.01.01_00.00.00.000"
    ).exists()


# --- Прогресс фазы "copy" ---

def test_progress_events_monotonic(src, dst):
    for i in range(10):
        (src / f"f{i}.txt").write_text("x")

    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    events: list[int] = []

    def on_progress(p):
        if p.phase == PHASE_COPY:
            events.append(p.processed)

    svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=True,
        on_progress=on_progress,
        on_done=lambda _r: done.set(),
        on_error=lambda _m: None,
    )
    assert done.wait(timeout=10)

    assert events[0] == 0
    assert events[-1] == 10
    assert events == sorted(events), "Прогресс должен расти"
    assert len(events) == 11


# --- Прогресс фаз "save_scan" / "save_store" ---

def test_save_scan_and_store_phases_emitted(src, dst):
    """При первом копировании есть обе подфазы."""
    (src / "a.txt").write_text("hello")

    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    phases: list[str] = []

    def on_progress(p):
        phases.append(p.phase)

    svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=True,
        on_progress=on_progress,
        on_done=lambda _r: done.set(),
        on_error=lambda _m: None,
    )
    assert done.wait(timeout=10)
    assert PHASE_SAVE_SCAN in phases
    assert PHASE_SAVE_STORE in phases


def test_save_scan_reports_n_files(src, dst):
    """Фаза scan идёт от 0 до N (N = файлов в destination)."""
    for i in range(3):
        (src / f"f{i}.txt").write_text(f"v{i}")

    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    scans: list[tuple[int, int]] = []

    def on_progress(p):
        if p.phase == PHASE_SAVE_SCAN:
            scans.append((p.processed, p.total))

    svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=True,
        on_progress=on_progress,
        on_done=lambda _r: done.set(),
        on_error=lambda _m: None,
    )
    assert done.wait(timeout=10)

    # state_before не создаётся (destination пуст, current нет),
    # поэтому scan идёт только для state_after: N=3.
    assert scans
    totals = {t for _, t in scans}
    assert 3 in totals
    assert scans[-1] == (3, 3)


def test_save_store_reports_m_new_blobs(src, dst):
    """Фаза store идёт от 0 до M (M = новых blob-ов)."""
    for i in range(3):
        (src / f"f{i}.txt").write_text(f"v{i}")

    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    stores: list[tuple[int, int]] = []

    def on_progress(p):
        if p.phase == PHASE_SAVE_STORE:
            stores.append((p.processed, p.total))

    svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=True,
        on_progress=on_progress,
        on_done=lambda _r: done.set(),
        on_error=lambda _m: None,
    )
    assert done.wait(timeout=10)

    # 3 новых blob-а в pool.
    assert stores
    totals = {t for _, t in stores}
    assert 3 in totals
    assert stores[-1] == (3, 3)


def test_save_store_skipped_when_no_new_blobs(
    src, dst, run_copy,
):
    """Повторное копирование без изменений: фаза store не
    эмитится, потому что нет новых blob-ов.

    Фаза scan эмитится легитимно: state_before сканирует
    destination, чтобы понять, отличается ли текущее состояние
    от current.state. Это реальная работа — и её прогресс
    должен быть виден пользователю. Если изменений нет,
    state_before не создаётся, и state_after тоже не нужен.
    """
    (src / "a.txt").write_text("hello")
    run_copy(src, dst, create_backup=True)

    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    phases: list[str] = []

    def on_progress(p):
        phases.append(p.phase)

    svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=True,
        on_progress=on_progress,
        on_done=lambda _r: done.set(),
        on_error=lambda _m: None,
    )
    assert done.wait(timeout=10)

    # save_scan — легитимно (проверка state_before).
    # save_store — не должен эмититься: новых blob-ов нет.
    assert PHASE_SAVE_STORE not in phases


def test_save_scan_and_store_on_replace(src, dst):
    """При замене: обе подфазы для before и after."""
    (src / "a.txt").write_text("new")
    (dst / "a.txt").write_text("old")

    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    scans: list[tuple[int, int]] = []
    stores: list[tuple[int, int]] = []

    def on_progress(p):
        if p.phase == PHASE_SAVE_SCAN:
            scans.append((p.processed, p.total))
        elif p.phase == PHASE_SAVE_STORE:
            stores.append((p.processed, p.total))

    svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=True,
        on_progress=on_progress,
        on_done=lambda _r: done.set(),
        on_error=lambda _m: None,
    )
    assert done.wait(timeout=10)

    # state_before: scan 1/1, store 1/1 (old → в pool).
    # state_after:  scan 1/1, store 1/1 (new → в pool).
    assert len(scans) >= 2
    assert len(stores) >= 2
    # Обе фазы доходят до 100% минимум по одному разу.
    assert any(s == (1, 1) for s in scans)
    assert any(s == (1, 1) for s in stores)


def test_no_save_phases_without_backup(src, dst):
    """create_backup=False → фазы scan/store не эмитятся."""
    (src / "a.txt").write_text("hello")

    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    phases: list[str] = []

    def on_progress(p):
        phases.append(p.phase)

    svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=False,
        on_progress=on_progress,
        on_done=lambda _r: done.set(),
        on_error=lambda _m: None,
    )
    assert done.wait(timeout=10)
    assert PHASE_SAVE_SCAN not in phases
    assert PHASE_SAVE_STORE not in phases


# --- Отмена с откатом ---

def test_cancel_rollback_full(src, dst, run_copy):
    for i in range(10):
        (src / f"existing_{i}.txt").write_text("new")
        (dst / f"existing_{i}.txt").write_text("old")
    for i in range(10):
        (src / f"new_{i}.txt").write_text("new")

    r = run_copy(
        src, dst, create_backup=True, cancel_after=8,
    )

    assert r.cancelled is True
    assert r.rollback_attempted is True
    assert r.rolled_back is True
    assert r.rollback_restored > 0
    assert r.rollback_errors == 0

    for i in range(10):
        content = (dst / f"existing_{i}.txt").read_text()
        assert content == "old", (
            f"existing_{i}: ожидалось 'old', получено {content!r}"
        )
    for i in range(10):
        assert not (dst / f"new_{i}.txt").exists(), (
            f"new_{i} не удалён после отката"
        )


def test_cancel_without_backup_no_rollback(
    src, dst, run_copy,
):
    """create_backup=False: state не создаётся, отката нет."""
    for i in range(10):
        (src / f"new_{i}.txt").write_text("new")

    r = run_copy(
        src, dst, create_backup=False, cancel_after=5,
    )

    assert r.cancelled is True
    assert r.rollback_attempted is False
    assert r.rolled_back is False

    new_count = sum(
        1 for i in range(10)
        if (dst / f"new_{i}.txt").exists()
    )
    assert new_count > 0


def test_cancel_rollback_empty_before(src, dst, run_copy):
    """До copy destination был пуст — state_before не создаётся,
    но откат всё равно удаляет созданные файлы."""
    for i in range(10):
        (src / f"new_{i}.txt").write_text("new")

    r = run_copy(
        src, dst, create_backup=True, cancel_after=5,
    )

    assert r.cancelled is True
    assert r.rollback_attempted is True
    assert r.rolled_back is True

    visible = [
        p for p in dst.iterdir()
        if p.name != CCRUN_DIR_NAME
    ]
    assert visible == []


def test_cancel_when_not_running():
    svc = CopyService()
    svc.cancel()


# --- Валидация ---

def test_validate_same_path(src):
    with pytest.raises(CopyValidationError, match="совпадают"):
        _validate(str(src), str(src))


def test_validate_dst_inside_src(src):
    inner = src / "sub"
    inner.mkdir()
    with pytest.raises(
        CopyValidationError, match="внутри исходной",
    ):
        _validate(str(src), str(inner))


def test_validate_src_inside_dst(src):
    outer = src / "outer"
    outer.mkdir()
    inner = outer / "inner"
    inner.mkdir()
    with pytest.raises(
        CopyValidationError, match="внутри целевой",
    ):
        _validate(str(inner), str(outer))


def test_validate_missing_source(tmp_path, dst):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(
        CopyValidationError, match="не найдена",
    ):
        _validate(str(missing), str(dst))


def test_validate_empty_source():
    with pytest.raises(
        CopyValidationError, match="исходная",
    ):
        _validate("", "/tmp")


def test_start_returns_false_on_conflict(src):
    svc = CopyService()
    errors: list[str] = []

    started = svc.start(
        source=str(src),
        destination=str(src),
        create_backup=True,
        on_progress=lambda _p: None,
        on_done=lambda _r: None,
        on_error=errors.append,
    )

    assert started is False
    assert len(errors) == 1
    assert "совпадают" in errors[0]


# --- format_cancel_status ---

def test_format_cancel_status_restored():
    r = CopyResult(
        cancelled=True,
        rollback_attempted=True,
        rolled_back=True,
        rollback_restored=5,
    )
    assert "восстановлены обратно" in format_cancel_status(r)


def test_format_cancel_status_deleted_only():
    r = CopyResult(
        cancelled=True,
        rollback_attempted=True,
        rolled_back=True,
        rollback_deleted=3,
    )
    assert "восстановлены обратно" in format_cancel_status(r)


def test_format_cancel_status_no_changes():
    r = CopyResult(
        cancelled=True,
        rollback_attempted=True,
        rolled_back=True,
    )
    assert "изменений не было" in format_cancel_status(r)


def test_format_cancel_status_partial():
    r = CopyResult(
        cancelled=True,
        rollback_attempted=True,
        rolled_back=False,
        rollback_errors=3,
    )
    msg = format_cancel_status(r)
    assert "откат неполный" in msg
    assert "3" in msg


def test_format_cancel_status_not_attempted():
    r = CopyResult(cancelled=True)
    assert format_cancel_status(r) == "Копирование отменено"


# --- format_copy_status ---

def test_format_copy_status_no_changes():
    r = CopyResult(copied=0, skipped=5)
    text = format_copy_status(r)
    assert "изменений нет" in text
    assert "5 файлов" in text
    assert "актуальны" in text


def test_format_copy_status_no_changes_single():
    r = CopyResult(copied=0, skipped=1)
    text = format_copy_status(r)
    assert "изменений нет" in text
    assert "1 файл" in text


def test_format_copy_status_no_changes_two():
    r = CopyResult(copied=0, skipped=2)
    text = format_copy_status(r)
    assert "2 файла" in text


def test_format_copy_status_empty_source():
    r = CopyResult(copied=0, skipped=0)
    assert "файлов в источнике нет" in format_copy_status(r)


def test_format_copy_status_normal():
    r = CopyResult(copied=3, skipped=5)
    text = format_copy_status(r)
    assert "скопировано 3" in text
    assert "пропущено 5" in text
    assert "изменений нет" not in text


def test_format_copy_status_with_state():
    r = CopyResult(
        copied=2, skipped=1,
        state_after_path=(
            "/tmp/state_2026.10.21_14.00.00.000.json"
        ),
    )
    text = format_copy_status(r)
    assert (
        "состояние: state_2026.10.21_14.00.00.000"
        in text
    )


def test_format_copy_status_mirror_changed_no_copy():
    r = CopyResult(
        copied=0, skipped=5,
        mirror_removed_files=2,
    )
    text = format_copy_status(r)
    assert "изменений нет" not in text
    assert "скопировано 0" in text
    assert "пропущено 5" in text


def test_format_copy_status_errors():
    r = CopyResult(copied=2, skipped=1, errors=3)
    text = format_copy_status(r)
    assert "ошибок 3" in text


def test_format_copy_status_cancelled():
    r = CopyResult(
        cancelled=True,
        rollback_attempted=True,
        rolled_back=True,
    )
    text = format_copy_status(r)
    assert "отменено" in text
    assert "изменений нет" not in text


# --- Кэш хэшей ---

def test_cache_created_after_copy(src, dst, run_copy):
    (src / "a.txt").write_text("hello")
    (src / "b.txt").write_text("world")

    run_copy(src, dst, create_backup=True)

    cache_path = dst / CCRUN_DIR_NAME / "hashes.json"
    assert cache_path.is_file()

    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["algorithm"] == "sha256"
    assert set(data["files"].keys()) == {"a.txt", "b.txt"}


def test_second_run_skips_hashing(src, dst, run_copy):
    (src / "a.txt").write_text("hello")
    (src / "b.txt").write_text("world")

    run_copy(src, dst, create_backup=True)
    cache_path = dst / CCRUN_DIR_NAME / "hashes.json"
    mtime_after_first = cache_path.stat().st_mtime_ns

    r = run_copy(src, dst, create_backup=True)
    assert r.copied == 0
    assert r.skipped == 2

    assert cache_path.stat().st_mtime_ns == mtime_after_first

# --- Дедупликация состояний ---

def test_state_before_reuses_existing(src, dst, run_copy):
    """Если destination совпадает с каким-то существующим
    state, state_before переиспользует его и не создаёт
    дубликат.

    Симулирует сценарий «current указывает не туда»: state
    уже есть в резервах, но current потерян/указывает на
    несуществующий state. Раньше создавался бы дубликат.
    """
    from services.cas.current_pointer import (
        CurrentData,
        CurrentPointer,
    )
    from services.cas.state_store import StateStore

    (src / "a.txt").write_text("v1")
    run_copy(src, dst)  # state A

    (src / "a.txt").write_text("v2")
    run_copy(src, dst)  # state B

    # Ломаем current.
    CurrentPointer(str(dst)).save(CurrentData(
        state="state_broken.json",
        last_action="copy",
        last_action_at="",
    ))

    states_before = len(StateStore(str(dst)).list())

    # Copy без изменений (source=v2=destination).
    run_copy(src, dst)

    states_after = len(StateStore(str(dst)).list())
    assert states_after == states_before, (
        f"Создано {states_after - states_before} "
        f"лишних state-файлов"
    )


def test_state_after_reuses_existing(src, dst, run_copy):
    """Если после copy состояние совпадает с существующим
    state — state_after переиспользует его."""
    from services.cas.state_store import StateStore

    (src / "a.txt").write_text("v1")
    run_copy(src, dst)  # state A

    (src / "a.txt").write_text("v2")
    run_copy(src, dst)  # state B (current=B)

    # Возвращаем destination в v1 (как будто пользователь
    # вручную откатил файл, не сделав restore).
    (dst / "a.txt").write_text("v1")
    # Source тоже возвращаем в v1 — copy без изменений.
    (src / "a.txt").write_text("v1")

    states_before = len(StateStore(str(dst)).list())

    run_copy(src, dst)

    states_after = len(StateStore(str(dst)).list())
    assert states_after == states_before, (
        f"Создано {states_after - states_before} "
        f"лишних state-файлов"
    )


def test_no_new_state_when_already_in_backups(
    src, dst, run_copy, run_restore,
):
    """Сценарий пользователя: восстановились, нажали copy
    без изменений — новой копии не появляется.

    states до restore = {A, B}.
    restore к A не создаёт restore_point (переиспользует B).
    copy без изменений не создаёт ни state_before,
    ни state_after.
    """
    from services.cas.state_store import StateStore

    (src / "a.txt").write_text("v1")
    r1 = run_copy(src, dst)  # A

    (src / "a.txt").write_text("v2")
    run_copy(src, dst)  # B

    states_before = len(StateStore(str(dst)).list())
    assert states_before == 2

    # Restore к A.
    run_restore(Path(r1.state_after_path).name, dst)

    states_after_restore = len(StateStore(str(dst)).list())
    assert states_after_restore == states_before, (
        f"Restore создал {states_after_restore - states_before} "
        f"лишних state"
    )

    # Source тоже возвращаем в v1 — copy без изменений.
    (src / "a.txt").write_text("v1")

    run_copy(src, dst)

    states_after_copy = len(StateStore(str(dst)).list())
    assert states_after_copy == states_before, (
        f"Copy создал {states_after_copy - states_before} "
        f"лишних state"
    )


def test_states_equal_mixed_separators():
    """_states_equal не различает / и \\ в путях."""
    from services.cas.state_store import (
        StateData,
        StateFile,
    )
    from services.copy.copy_service import _CopyWorker

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

    assert _CopyWorker._states_equal(a, b) is True
