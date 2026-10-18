"""Тесты сервиса копирования.

Покрытие:
  • копирование новых файлов;
  • пропуск идентичных;
  • замена с бэкапом и без;
  • манифест;
  • служебные папки !CCRun и !Backup_* в источнике;
  • отмена с откатом;
  • отмена без бэкапа (корректно репортится);
  • тексты format_cancel_status;
  • валидация путей.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from services.copy_service import (
    CopyProgress,
    CopyResult,
    CopyService,
    CopyValidationError,
    _validate,
    format_cancel_status,
)

# --- Базовые типы ---

def test_result_defaults():
    r = CopyResult()
    assert r.total == 0
    assert r.copied == 0
    assert r.skipped == 0
    assert r.errors == 0
    assert r.backup_dir is None
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


# --- Копирование: без замен ---

def test_empty_source(src, dst, run_copy):
    r = run_copy(src, dst, create_backup=True)
    assert r.total == 0
    assert r.copied == 0
    assert r.skipped == 0
    assert r.backup_dir is None
    assert list(dst.iterdir()) == []


def test_new_files_no_backup(src, dst, run_copy):
    (src / "a.txt").write_text("1")
    (src / "b.txt").write_text("2")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 2
    assert r.copied == 2
    assert r.skipped == 0
    assert r.backup_dir is None
    assert (dst / "a.txt").read_text() == "1"
    assert (dst / "b.txt").read_text() == "2"


def test_identical_files_skipped(src, dst, run_copy):
    (src / "a.txt").write_text("same")
    shutil.copy2(src / "a.txt", dst / "a.txt")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 1
    assert r.copied == 0
    assert r.skipped == 1
    assert r.backup_dir is None


def test_nested_directories(src, dst, run_copy):
    (src / "sub1" / "sub2").mkdir(parents=True)
    (src / "sub1" / "sub2" / "deep.txt").write_text("deep")
    (src / "top.txt").write_text("top")

    r = run_copy(src, dst, create_backup=True)

    assert r.copied == 2
    assert (dst / "sub1" / "sub2" / "deep.txt").read_text() == "deep"
    assert (dst / "top.txt").read_text() == "top"


# --- Замена с бэкапом ---

def test_replaced_file_with_backup(src, dst, run_copy):
    (src / "a.txt").write_text("new")
    (dst / "a.txt").write_text("old")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 1
    assert r.copied == 1
    assert r.backup_dir is not None
    assert (dst / "a.txt").read_text() == "new"

    backup = Path(r.backup_dir)
    assert (backup / "a.txt").read_text() == "old"

    ccrun = backup / "!CCRun"
    assert ccrun.is_dir()
    manifest_path = ccrun / "manifest.json"
    assert manifest_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == 1
    assert manifest["app"] == "CheckCopyRun"
    assert manifest["source"] == str(src)
    assert manifest["destination"] == str(dst)
    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["path"] == "a.txt"
    assert manifest["files"][0]["action"] == "replaced"
    assert manifest["summary"]["backed_up"] == 1
    assert manifest["summary"]["copied"] == 1
    assert manifest["summary"]["cancelled"] is False


def test_replaced_file_without_backup(src, dst, run_copy):
    (src / "a.txt").write_text("new")
    (dst / "a.txt").write_text("old")

    r = run_copy(src, dst, create_backup=False)

    assert r.copied == 1
    assert r.backup_dir is None
    assert (dst / "a.txt").read_text() == "new"


def test_backup_name_format(src, dst, run_copy):
    import re

    (src / "a.txt").write_text("new")
    (dst / "a.txt").write_text("old")

    r = run_copy(src, dst, create_backup=True)
    assert r.backup_dir is not None

    name = Path(r.backup_dir).name
    pattern = r"^!Backup_\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}\.\d{3}$"
    assert re.match(pattern, name), f"Формат: {name!r}"


# --- Служебные папки в source ---

def test_ccrun_skipped_in_source(src, dst, run_copy):
    (src / "!CCRun").mkdir()
    (src / "!CCRun" / "info.txt").write_text("meta")
    (src / "a.txt").write_text("hello")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 1
    assert not (dst / "!CCRun").exists()


def test_backup_dirs_skipped_in_source(src, dst, run_copy):
    (src / "!Backup_2025.01.01_00.00.00.000").mkdir()
    (src / "!Backup_2025.01.01_00.00.00.000" / "old.txt").write_text("x")
    (src / "a.txt").write_text("hello")

    r = run_copy(src, dst, create_backup=True)

    assert r.total == 1
    assert not (dst / "!Backup_2025.01.01_00.00.00.000").exists()


# --- Прогресс ---

def test_progress_events_monotonic(src, dst):
    import threading

    for i in range(10):
        (src / f"f{i}.txt").write_text("x")

    svc = CopyService(scheduler=lambda fn: fn())
    done = threading.Event()
    events: list[int] = []

    svc.start(
        source=str(src),
        destination=str(dst),
        create_backup=True,
        on_progress=lambda p: events.append(p.processed),
        on_done=lambda _r: done.set(),
        on_error=lambda _m: None,
    )
    assert done.wait(timeout=10)

    assert events[0] == 0
    assert events[-1] == 10
    assert events == sorted(events), "Прогресс должен расти"
    assert len(events) == 11


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


def test_cancel_without_backup_new_files_deleted(src, dst, run_copy):
    for i in range(10):
        (src / f"new_{i}.txt").write_text("new")

    r = run_copy(
        src, dst, create_backup=False, cancel_after=5,
    )

    assert r.cancelled is True
    assert r.rollback_attempted is True
    assert r.rolled_back is True
    assert r.rollback_deleted > 0
    assert r.rollback_errors == 0

    assert list(dst.iterdir()) == []


def test_cancel_without_backup_reports_errors(src, dst, run_copy):
    """Отмена без бэкапа: заменённые файлы восстановить нельзя.

    После фикса: такие замены попадают в rollback_errors,
    rolled_back = False. Пользователь видит, что откат неполный.
    """
    for i in range(20):
        (src / f"f{i}.txt").write_text("new")
        (dst / f"f{i}.txt").write_text("old")

    r = run_copy(
        src, dst, create_backup=False, cancel_after=5,
    )

    assert r.cancelled is True
    assert r.rollback_attempted is True
    assert r.backup_dir is None
    assert r.rolled_back is False
    assert r.rollback_errors > 0

    # Хотя бы часть файлов осталась новой — их не вернуть.
    new_count = sum(
        1 for i in range(20)
        if (dst / f"f{i}.txt").read_text() == "new"
    )
    assert new_count > 0, (
        "Ожидали, что хотя бы некоторые замены произошли до отмены"
    )

    # format_cancel_status сообщает пользователю про неполный откат.
    msg = format_cancel_status(r)
    assert "откат неполный" in msg


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
    with pytest.raises(CopyValidationError, match="внутри исходной"):
        _validate(str(src), str(inner))


def test_validate_src_inside_dst(src):
    outer = src / "outer"
    outer.mkdir()
    inner = outer / "inner"
    inner.mkdir()
    with pytest.raises(CopyValidationError, match="внутри целевой"):
        _validate(str(inner), str(outer))


def test_validate_missing_source(tmp_path, dst):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(CopyValidationError, match="не найдена"):
        _validate(str(missing), str(dst))


def test_validate_empty_source():
    with pytest.raises(CopyValidationError, match="исходная"):
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

# --- Кэш хэшей ---

def test_cache_created_after_copy(src, dst, run_copy):
    """После первого копирования в !CCRun/hashes.json есть записи."""
    (src / "a.txt").write_text("hello")
    (src / "b.txt").write_text("world")

    run_copy(src, dst, create_backup=True)

    cache_path = dst / "!CCRun" / "hashes.json"
    assert cache_path.is_file()

    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["algorithm"] == "sha256"
    assert set(data["files"].keys()) == {"a.txt", "b.txt"}


def test_second_run_skips_hashing(src, dst, run_copy):
    """Второй запуск без изменений не пересчитывает хэши и не
    перезаписывает кэш."""
    (src / "a.txt").write_text("hello")
    (src / "b.txt").write_text("world")

    run_copy(src, dst, create_backup=True)
    cache_path = dst / "!CCRun" / "hashes.json"
    mtime_after_first = cache_path.stat().st_mtime_ns

    # Второй прогон — все файлы идентичны, изменения кэша быть
    # не должно.
    r = run_copy(src, dst, create_backup=True)
    assert r.copied == 0
    assert r.skipped == 2

    assert cache_path.stat().st_mtime_ns == mtime_after_first
