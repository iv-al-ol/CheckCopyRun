"""Тесты запуска .exe на длинных путях.

Проверяем контракт `launch_exe`:
  • короткие пути работают как раньше;
  • длинные — проходят проверку существования
    (`long_io.isfile`), `Popen` вызывается с именем файла и
    cwd = родительская папка. Реальный процесс не запускаем —
    подменяем `subprocess.Popen`;
  • отсутствующий файл — LaunchError «не найден»;
  • не .exe — LaunchError «не является .exe».
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from core import long_io
from services.system.launcher import LaunchError, launch_exe

_WINDOWS = sys.platform == "win32"

pytestmark = pytest.mark.skipif(
    not _WINDOWS, reason="Windows-only",
)


def _make_deep_root(tmp_path: Path, prefix: str = "a") -> Path:
    name = "a" * 60
    deep = tmp_path / prefix
    for _ in range(4):
        deep = deep / name
    long_io.makedirs(str(deep), exist_ok=True)
    assert len(str(deep)) >= 260
    return deep


def _record_popen(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    def fake(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake)
    return calls


# --- Короткий путь ---

def test_short_path_popen_uses_name_and_cwd(
    monkeypatch, tmp_path,
):
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"MZ")

    calls = _record_popen(monkeypatch)
    launch_exe(str(exe))

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["app.exe"]
    assert kwargs["cwd"] == str(tmp_path)


# --- Длинный путь ---

def test_long_path_passes_check_and_uses_cwd(
    monkeypatch, tmp_path,
):
    deep = _make_deep_root(tmp_path)
    exe = deep / "app.exe"
    with long_io.open(str(exe), "wb") as f:
        f.write(b"MZ")

    calls = _record_popen(monkeypatch)
    launch_exe(str(exe))

    assert len(calls) == 1
    args, kwargs = calls[0]
    # Имя без пути — CreateProcessW разрешает его
    # относительно cwd.
    assert args == ["app.exe"]
    # cwd — длинная родительская папка (может быть
    # `\\?\`-префиксованной после long_io.abspath, но
    # тут — без префикса: display_path срезал).
    assert kwargs["cwd"] == str(deep)


# --- Ошибки ---

def test_missing_file_raises(monkeypatch, tmp_path):
    missing = tmp_path / "ghost.exe"
    calls = _record_popen(monkeypatch)

    with pytest.raises(LaunchError, match="не найден"):
        launch_exe(str(missing))

    assert calls == []


def test_long_missing_file_raises(monkeypatch, tmp_path):
    deep = _make_deep_root(tmp_path)
    missing = deep / "ghost.exe"
    calls = _record_popen(monkeypatch)

    with pytest.raises(LaunchError, match="не найден"):
        launch_exe(str(missing))

    assert calls == []


def test_not_exe_raises(monkeypatch, tmp_path):
    bad = tmp_path / "readme.txt"
    bad.write_text("hello")
    calls = _record_popen(monkeypatch)

    with pytest.raises(LaunchError, match=r"не является \.exe"):
        launch_exe(str(bad))

    assert calls == []


def test_empty_path_raises(monkeypatch):
    _record_popen(monkeypatch)
    with pytest.raises(LaunchError, match="не задан"):
        launch_exe("")


# --- Popen падает → LaunchError с текстом ---

def test_popen_error_wrapped(monkeypatch, tmp_path):
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"MZ")

    def boom(*_args, **_kwargs):
        raise OSError(206, "The filename or extension is too long")

    monkeypatch.setattr(subprocess, "Popen", boom)

    with pytest.raises(LaunchError) as exc_info:
        launch_exe(str(exe))

    msg = str(exc_info.value)
    assert "путь слишком длинный" in msg.lower() or "too long" in msg.lower()
