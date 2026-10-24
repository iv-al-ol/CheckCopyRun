"""Тесты автопроверки: выбор кандидатов и _is_restored."""

from __future__ import annotations

import shutil
from pathlib import Path

from core.models import Profile
from services.cas.current_pointer import CurrentPointer
from services.startup_check import (
    _is_restored,
    select_startup_candidates,
)


def _make_profile(
    tmp_path: Path,
    *,
    name: str,
    check_on_startup: bool = True,
) -> Profile:
    src = tmp_path / f"src_{name}"
    dst = tmp_path / f"dst_{name}"
    src.mkdir()
    dst.mkdir()
    return Profile(
        name_base=name,
        source=str(src),
        destination=str(dst),
        check_on_startup=check_on_startup,
    )


def _mark_restored(destination: str) -> None:
    cp = CurrentPointer(destination)
    cp.save_restore("state_x.json", restored_from="state_x.json")


def _mark_copy(destination: str) -> None:
    cp = CurrentPointer(destination)
    cp.save_copy("state_x.json")


# --- _is_restored ---

def test_is_restored_missing(tmp_path):
    dst = tmp_path / "empty_dst"
    dst.mkdir()
    assert _is_restored(str(dst)) is False


def test_is_restored_copy(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    _mark_copy(str(dst))
    assert _is_restored(str(dst)) is False


def test_is_restored_restore(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    _mark_restored(str(dst))
    assert _is_restored(str(dst)) is True


def test_is_restored_empty_path():
    assert _is_restored("") is False


# --- select_startup_candidates ---

def test_select_no_candidates(tmp_path):
    p = _make_profile(
        tmp_path, name="a", check_on_startup=False,
    )
    cands, skipped = select_startup_candidates(
        [p], run_on_restored=False,
    )
    assert cands == []
    assert skipped == 0


def test_select_plain_profile(tmp_path):
    p = _make_profile(tmp_path, name="a")
    cands, skipped = select_startup_candidates(
        [p], run_on_restored=False,
    )
    assert cands == [p]
    assert skipped == 0


def test_select_restored_skipped_by_default(tmp_path):
    p = _make_profile(tmp_path, name="a")
    _mark_restored(p.destination)
    cands, skipped = select_startup_candidates(
        [p], run_on_restored=False,
    )
    assert cands == []
    assert skipped == 1


def test_select_restored_included_when_enabled(tmp_path):
    p = _make_profile(tmp_path, name="a")
    _mark_restored(p.destination)
    cands, skipped = select_startup_candidates(
        [p], run_on_restored=True,
    )
    assert cands == [p]
    assert skipped == 0


def test_select_mixed(tmp_path):
    p1 = _make_profile(tmp_path, name="plain")
    p2 = _make_profile(tmp_path, name="restored")
    _mark_restored(p2.destination)
    p3 = _make_profile(
        tmp_path, name="no_autocheck", check_on_startup=False,
    )
    _mark_restored(p3.destination)

    cands, skipped = select_startup_candidates(
        [p1, p2, p3], run_on_restored=False,
    )
    # p1 — обычный, попадает.
    # p2 — восстановлен, пропущен.
    # p3 — check_on_startup=False, не попадает вообще.
    assert p1 in cands
    assert p2 not in cands
    assert p3 not in cands
    assert skipped == 1


def test_select_mixed_included(tmp_path):
    """При run_on_restored=True оба профиля попадают.

    Profile — обычный dataclass без frozen=True, поэтому
    unhashable (__hash__ = None). Сравниваем списки — порядок
    сохраняется, select_startup_candidates не сортирует.
    """
    p1 = _make_profile(tmp_path, name="plain")
    p2 = _make_profile(tmp_path, name="restored")
    _mark_restored(p2.destination)

    cands, skipped = select_startup_candidates(
        [p1, p2], run_on_restored=True,
    )
    assert cands == [p1, p2]
    assert skipped == 0


def test_select_profile_without_source(tmp_path):
    """can_copy() = False (нет source-директории) — не кандидат."""
    p = _make_profile(tmp_path, name="broken")
    # Ломаем source.
    shutil.rmtree(p.source)
    cands, skipped = select_startup_candidates(
        [p], run_on_restored=False,
    )
    assert cands == []
    assert skipped == 0
