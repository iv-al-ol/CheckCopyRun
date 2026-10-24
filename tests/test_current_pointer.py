"""Тесты current.json."""

from __future__ import annotations

from services.copy_constants import CURRENT_FILENAME
from services.current_pointer import (
    CurrentData,
    CurrentPointer,
)


def test_missing(tmp_path):
    p = CurrentPointer(str(tmp_path))
    assert p.load() is None


def test_save_and_load(tmp_path):
    p = CurrentPointer(str(tmp_path))
    p.save(CurrentData(
        state="state_2026.10.20_14.18.10.123.json",
        last_action="copy",
        last_action_at="2026-10-20T14:18:10.123",
    ))
    data = p.load()
    assert data is not None
    assert data.state == "state_2026.10.20_14.18.10.123.json"
    assert data.last_action == "copy"
    assert data.last_action_at == "2026-10-20T14:18:10.123"


def test_save_copy(tmp_path):
    p = CurrentPointer(str(tmp_path))
    p.save_copy("state_x.json")
    data = p.load()
    assert data is not None
    assert data.last_action == "copy"
    assert data.state == "state_x.json"
    assert data.last_action_at
    assert data.restored_from == ""


def test_save_restore(tmp_path):
    p = CurrentPointer(str(tmp_path))
    p.save_restore(
        "state_now.json", "state_old.json",
    )
    data = p.load()
    assert data is not None
    assert data.last_action == "restore"
    assert data.state == "state_now.json"
    assert data.restored_from == "state_old.json"


def test_save_initial(tmp_path):
    p = CurrentPointer(str(tmp_path))
    p.save_initial("state_first.json")
    data = p.load()
    assert data is not None
    assert data.last_action == "initial"


def test_overwrite(tmp_path):
    p = CurrentPointer(str(tmp_path))
    p.save_copy("state_a.json")
    p.save_copy("state_b.json")
    data = p.load()
    assert data is not None
    assert data.state == "state_b.json"


def test_corrupted(tmp_path):
    p = CurrentPointer(str(tmp_path))
    p.path.parent.mkdir(parents=True, exist_ok=True)
    p.path.write_text("not json {", encoding="utf-8")
    assert p.load() is None


def test_file_name(tmp_path):
    p = CurrentPointer(str(tmp_path))
    assert p.path.name == CURRENT_FILENAME
