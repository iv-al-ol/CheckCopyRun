"""Тесты метки текущей версии destination (CAS)."""

from __future__ import annotations

import time

from services.current_pointer import CurrentPointer
from services.destination_state import (
    build_label,
    save_after_copy,
    save_after_restore,
)


def _patch_time(monkeypatch, iso: str) -> None:
    """Мокает now_iso во всех модулях, где он используется.

    Нужно, чтобы timestamp'ы в state-файлах и в current.json
    были предсказуемы. Модули:
      • current_pointer — last_action_at;
      • state_store — created_at fallback в store.create;
      • state_scanner — created_at в scan_destination.
    """
    import services.current_pointer as cp_mod
    import services.state_scanner as sc_mod
    import services.state_store as ss_mod

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
    assert "Текущая версия файлов от" in label


# --- Copy / Initial ---

def test_current_copy(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("x")

    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    label = build_label(str(tmp_path))
    assert label == "Текущая версия файлов от 20.10.2026 14:18:10"


def test_current_initial(tmp_path, monkeypatch):
    """save_after_copy без предшествующего — обычная метка."""
    (tmp_path / "a.txt").write_text("x")

    _patch_time(monkeypatch, "2026-10-20T14:18:10.000")
    save_after_copy(str(tmp_path))

    label = build_label(str(tmp_path))
    assert label == "Текущая версия файлов от 20.10.2026 14:18:10"


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

    assert "(восстановлена резервная копия)" in label
    assert "20.10.2026 14:18:10" in label


# --- Manual edit detection ---

def test_manually_edited_mtime(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    save_after_copy(str(tmp_path))

    time.sleep(0.1)
    (tmp_path / "a.txt").write_text("y")

    label = build_label(str(tmp_path))
    assert "изменена вручную" in label


def test_extra_file_detected_as_manual(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    save_after_copy(str(tmp_path))

    (tmp_path / "extra.txt").write_text("y")

    label = build_label(str(tmp_path))
    assert "изменена вручную" in label


def test_missing_file_detected_as_manual(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("y")
    save_after_copy(str(tmp_path))

    (tmp_path / "a.txt").unlink()

    label = build_label(str(tmp_path))
    assert "изменена вручную" in label


def test_ccrun_excluded_from_manual_check(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    save_after_copy(str(tmp_path))

    # Мусор в !CCRun не считается ручной правкой.
    ccrun = tmp_path / "!CCRun"
    ccrun.mkdir(exist_ok=True)
    (ccrun / "debug.log").write_text("log")

    label = build_label(str(tmp_path))
    assert "изменена вручную" not in label
