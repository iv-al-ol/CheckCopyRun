"""Тесты IconPickerState — без tkinter."""

from __future__ import annotations

import hashlib
from pathlib import Path

from config.constants import DEFAULT_PROFILE_ICON
from ui.components.icon_picker.state import IconPickerState

# --- Помощники ---

def _fake_saver_ok(png_path: Path):
    """Возвращает функцию-saver, которая создаёт файл и отдаёт его."""
    def saver(exe_path: Path, out_dir: Path) -> Path | None:
        out_dir.mkdir(parents=True, exist_ok=True)
        png = out_dir / f"exe_{exe_path.stem}.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        return png
    return saver


def _fake_saver_fail():
    """Saver, который всегда возвращает None."""
    def saver(exe_path: Path, out_dir: Path) -> Path | None:
        return None
    return saver


def _make_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"MZ")
    return exe


def _make_state(
    tmp_path: Path,
    *,
    current_icon: str = "",
    current_icon_auto: bool = False,
    exe_path: Path | None = None,
    saver=None,
) -> IconPickerState:
    icons_dir = tmp_path / "icons"
    return IconPickerState(
        current_icon=current_icon,
        current_icon_auto=current_icon_auto,
        exe_path=exe_path,
        icons_dir=icons_dir,
        exe_icon_saver=saver if saver is not None else _fake_saver_ok(None),
    )


# --- Начальное состояние ---

def test_initial_empty_uses_default(tmp_path):
    state = _make_state(tmp_path)
    assert state.selected_kind == "emoji"
    assert state.selected_value == DEFAULT_PROFILE_ICON


def test_initial_emoji(tmp_path):
    state = _make_state(tmp_path, current_icon="🚀")
    assert state.selected_kind == "emoji"
    assert state.selected_value == "🚀"


def test_initial_file_path(tmp_path):
    path = str(tmp_path / "icon.png")
    state = _make_state(tmp_path, current_icon=path)
    assert state.selected_kind == "file"
    assert state.selected_value == path


def test_initial_auto_with_cached_png(tmp_path):
    """auto + exe + уже есть кэш PNG → начинаем в auto."""
    exe = _make_exe(tmp_path)
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()

    digest = hashlib.sha256(
        str(exe.resolve()).encode("utf-8"),
    ).hexdigest()[:16]
    cached = icons_dir / f"exe_{digest}.png"
    cached.write_bytes(b"\x89PNG\r\n\x1a\n")

    state = _make_state(
        tmp_path,
        current_icon=str(cached),
        current_icon_auto=True,
        exe_path=exe,
    )
    assert state.selected_kind == "auto"
    assert state.selected_value == str(cached)
    assert state.is_auto is True


def test_initial_auto_no_cache_falls_to_emoji(tmp_path):
    """auto + exe, но кэша нет → дефолтная эмодзи."""
    exe = _make_exe(tmp_path)
    state = _make_state(
        tmp_path,
        current_icon=str(tmp_path / "gone.png"),
        current_icon_auto=True,
        exe_path=exe,
    )
    assert state.selected_kind == "emoji"
    assert state.selected_value == DEFAULT_PROFILE_ICON


def test_initial_auto_no_exe_falls_to_emoji(tmp_path):
    """current_icon_auto=True, но exe не задан → дефолт."""
    state = _make_state(
        tmp_path,
        current_icon="🚀",
        current_icon_auto=True,
        exe_path=None,
    )
    assert state.selected_kind == "emoji"
    assert state.selected_value == "🚀"


# --- select_emoji ---

def test_select_emoji_switches_kind(tmp_path):
    path = str(tmp_path / "icon.png")
    state = _make_state(tmp_path, current_icon=path)

    state.select_emoji("🎯")

    assert state.selected_kind == "emoji"
    assert state.selected_value == "🎯"


def test_select_emoji_empty_string_uses_default(tmp_path):
    state = _make_state(tmp_path, current_icon="🚀")
    state.select_emoji("")
    assert state.selected_value == DEFAULT_PROFILE_ICON


# --- select_file_as_image ---

def test_select_file_as_image(tmp_path):
    path = str(tmp_path / "pic.png")
    state = _make_state(tmp_path, current_icon="🚀")

    state.select_file_as_image(path)

    assert state.selected_kind == "file"
    assert state.selected_value == path


# --- select_file_from_exe ---

def test_select_file_from_exe_success(tmp_path):
    exe = _make_exe(tmp_path)
    state = _make_state(tmp_path, saver=_fake_saver_ok(None))

    ok, err = state.select_file_from_exe(exe)

    assert ok is True
    assert err == ""
    assert state.selected_kind == "file"
    assert state.is_auto is False


def test_select_file_from_exe_failure(tmp_path):
    exe = _make_exe(tmp_path)
    state = _make_state(
        tmp_path,
        current_icon="🚀",
        saver=_fake_saver_fail(),
    )

    ok, err = state.select_file_from_exe(exe)

    assert ok is False
    assert "Не удалось извлечь иконку" in err
    # Состояние не изменилось.
    assert state.selected_kind == "emoji"
    assert state.selected_value == "🚀"


# --- try_enable_auto ---

def test_enable_auto_success(tmp_path):
    exe = _make_exe(tmp_path)
    state = _make_state(
        tmp_path,
        current_icon="🚀",
        exe_path=exe,
        saver=_fake_saver_ok(None),
    )

    ok, err = state.try_enable_auto()

    assert ok is True
    assert err == ""
    assert state.selected_kind == "auto"
    assert state.is_auto is True


def test_enable_auto_without_exe(tmp_path):
    state = _make_state(
        tmp_path,
        current_icon="🚀",
        exe_path=None,
    )

    ok, err = state.try_enable_auto()

    assert ok is False
    assert "Приложение не выбрано" in err
    assert state.selected_kind == "emoji"


def test_enable_auto_missing_exe_file(tmp_path):
    missing = tmp_path / "ghost.exe"
    state = _make_state(
        tmp_path,
        current_icon="🚀",
        exe_path=missing,
    )

    ok, err = state.try_enable_auto()

    assert ok is False
    assert "не найден" in err


def test_enable_auto_extraction_fails(tmp_path):
    exe = _make_exe(tmp_path)
    state = _make_state(
        tmp_path,
        current_icon="🚀",
        exe_path=exe,
        saver=_fake_saver_fail(),
    )

    ok, err = state.try_enable_auto()

    assert ok is False
    assert "Не удалось извлечь иконку" in err
    assert state.selected_kind == "emoji"


# --- disable_auto ---

def test_disable_auto_from_auto(tmp_path):
    exe = _make_exe(tmp_path)
    state = _make_state(
        tmp_path,
        current_icon="🚀",
        exe_path=exe,
        saver=_fake_saver_ok(None),
    )
    state.try_enable_auto()
    assert state.is_auto is True

    state.disable_auto()

    assert state.selected_kind == "emoji"
    assert state.selected_value == DEFAULT_PROFILE_ICON


def test_disable_auto_when_not_auto_is_noop(tmp_path):
    state = _make_state(tmp_path, current_icon="🚀")

    state.disable_auto()

    assert state.selected_kind == "emoji"
    assert state.selected_value == "🚀"


# --- auto_available ---

def test_auto_available_true_with_exe(tmp_path):
    exe = _make_exe(tmp_path)
    state = _make_state(tmp_path, exe_path=exe)
    assert state.auto_available is True


def test_auto_available_false_without_exe(tmp_path):
    state = _make_state(tmp_path, exe_path=None)
    assert state.auto_available is False


def test_auto_available_false_with_missing_exe(tmp_path):
    missing = tmp_path / "ghost.exe"
    state = _make_state(tmp_path, exe_path=missing)
    assert state.auto_available is False


# --- build_result ---

def test_build_result_emoji(tmp_path):
    state = _make_state(tmp_path, current_icon="🚀")
    assert state.build_result() == ("🚀", False)


def test_build_result_file(tmp_path):
    path = str(tmp_path / "pic.png")
    state = _make_state(tmp_path, current_icon=path)
    assert state.build_result() == (path, False)


def test_build_result_auto(tmp_path):
    exe = _make_exe(tmp_path)
    state = _make_state(
        tmp_path,
        current_icon="🚀",
        exe_path=exe,
        saver=_fake_saver_ok(None),
    )
    state.try_enable_auto()
    icon, icon_auto = state.build_result()
    assert icon_auto is True
    assert icon.startswith(str(tmp_path / "icons"))


def test_build_result_empty_value_uses_default(tmp_path):
    """Защита: пустая строка никогда не уходит в профиль."""
    state = _make_state(tmp_path)
    state._value = ""
    icon, icon_auto = state.build_result()
    assert icon == DEFAULT_PROFILE_ICON
    assert icon_auto is False
