"""Тесты метки текущей версии destination (CAS)."""

from __future__ import annotations

import time

from services.cas.current_pointer import CurrentData, CurrentPointer
from services.cas.destination_state import (
    build_label,
    save_after_copy,
    save_after_restore,
)


def _patch_time(monkeypatch, iso: str) -> None:
    """Мокает now_iso во всех модулях, где он используется."""
    import services.cas.current_pointer as cp_mod
    import services.cas.state_scanner as sc_mod
    import services.cas.state_store as ss_mod

    monkeypatch.setattr(cp_mod, "now_iso", lambda: iso)
    monkeypatch.setattr(ss_mod, "now_iso", lambda: iso)
    monkeypatch.setattr(sc_mod, "now_iso", lambda: iso)


# --- База ---

def test_no_destination(tmp_path):
    assert build_label("") == ""
    assert build_label(str(tmp_path / "missing")) == ""


def test_no_state_fallback_to_mtime(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    label = build_label(str(tmp_path))
    assert "Текущая версия от" in label


# --- Copy ---

def test_current_copy(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("x")

    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    label = build_label(str(tmp_path))
    assert label == "Текущая версия от 20.10.2026 14:18:10"


def test_current_initial(tmp_path, monkeypatch):
    """save_after_copy без предшествующего — обычная метка."""
    (tmp_path / "a.txt").write_text("x")

    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    label = build_label(str(tmp_path))
    assert label == "Текущая версия от 20.10.2026 14:18:10"


# --- Restore ---

def test_current_restore(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("x")

    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    cur = CurrentPointer(str(tmp_path)).load()
    assert cur is not None
    state_name = cur.state

    save_after_restore(str(tmp_path), state_name)
    label = build_label(str(tmp_path))

    assert label == (
        "Текущая версия от 20.10.2026 14:18:10 "
        "— восстановлено из бэкапа"
    )


# --- Rollback ---

def test_current_rollback(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("x")

    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    cur = CurrentPointer(str(tmp_path)).load()
    assert cur is not None
    state_name = cur.state

    CurrentPointer(str(tmp_path)).save(CurrentData(
        state=state_name,
        last_action="rollback",
        last_action_at="",
    ))

    label = build_label(str(tmp_path))
    assert label == (
        "Текущая версия от 20.10.2026 14:18:10 "
        "— откат после отмены"
    )


# --- Ручные правки ---

def test_manually_edited_mtime(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    save_after_copy(str(tmp_path))

    time.sleep(0.1)
    (tmp_path / "a.txt").write_text("y")

    label = build_label(str(tmp_path))
    assert label.startswith("Текущая версия от ")
    assert "— изменено вручную" in label
    assert "после восстановления из бэкапа" not in label
    assert "после отката" not in label


def test_extra_file_detected_as_manual(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    save_after_copy(str(tmp_path))

    (tmp_path / "extra.txt").write_text("y")

    label = build_label(str(tmp_path))
    assert "изменено вручную" in label


def test_missing_file_detected_as_manual(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("y")
    save_after_copy(str(tmp_path))

    (tmp_path / "a.txt").unlink()

    label = build_label(str(tmp_path))
    assert "изменено вручную" in label


def test_ccrun_excluded_from_manual_check(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    save_after_copy(str(tmp_path))

    ccrun = tmp_path / "!CCRun"
    ccrun.mkdir(exist_ok=True)
    (ccrun / "debug.log").write_text("log")

    label = build_label(str(tmp_path))
    assert "изменено вручную" not in label


def test_manual_edit_after_restore(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("v1")

    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    cur = CurrentPointer(str(tmp_path)).load()
    assert cur is not None
    state_name = cur.state

    save_after_restore(str(tmp_path), state_name)

    time.sleep(0.1)
    (tmp_path / "a.txt").write_text("v2")

    label = build_label(str(tmp_path))
    assert label.startswith("Текущая версия от ")
    assert "изменено вручную" in label
    assert "после восстановления из бэкапа" in label


def test_manual_edit_after_rollback(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("v1")

    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    cur = CurrentPointer(str(tmp_path)).load()
    assert cur is not None
    state_name = cur.state

    CurrentPointer(str(tmp_path)).save(CurrentData(
        state=state_name,
        last_action="rollback",
        last_action_at="",
    ))

    time.sleep(0.1)
    (tmp_path / "a.txt").write_text("v2")

    label = build_label(str(tmp_path))
    assert label.startswith("Текущая версия от ")
    assert "изменено вручную" in label
    assert "после отката" in label


def test_manual_edit_after_copy_no_restore_mention(
    tmp_path, monkeypatch,
):
    (tmp_path / "a.txt").write_text("v1")

    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    time.sleep(0.1)
    (tmp_path / "a.txt").write_text("v2")

    label = build_label(str(tmp_path))
    assert "изменено вручную" in label
    assert "после восстановления из бэкапа" not in label
    assert "после отката" not in label


# --- Пустая папка ---

def test_empty_folder(tmp_path, monkeypatch):
    """Пустая папка, пустой state — «Папка пуста»."""
    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    label = build_label(str(tmp_path))
    assert label == "Папка пуста"


def test_empty_folder_after_restore(tmp_path, monkeypatch):
    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    cur = CurrentPointer(str(tmp_path)).load()
    assert cur is not None
    state_name = cur.state

    save_after_restore(str(tmp_path), state_name)

    label = build_label(str(tmp_path))
    assert label == "Папка пуста"


def test_empty_folder_then_file_added(
    tmp_path, monkeypatch,
):
    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    # Добавили файл вручную — уже не «папка пуста»,
    # а «изменено вручную».
    (tmp_path / "new.txt").write_text("x")

    label = build_label(str(tmp_path))
    assert "изменено вручную" in label
