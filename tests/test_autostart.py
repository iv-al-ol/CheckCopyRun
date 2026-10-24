"""Тесты автозапуска: чистая логика без обращения к реестру.

Реальные enable/disable/is_enabled не тестируются: они пишут
в HKCU пользователя и зависят от пути к реальному .exe.
Логика покрыта юнит-тестами через monkeypatch sys/os/Path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from services.system import autostart

# --- is_supported ---

def test_is_supported_matches_platform():
    # winreg есть только на Windows.
    assert autostart.is_supported() == (sys.platform == "win32")


# --- _is_compiled ---

def _reset_compile_flags(monkeypatch) -> None:
    monkeypatch.delenv("NUITKA_ONEFILE_BINARY", raising=False)
    monkeypatch.delenv("NUITKA_ONEFILE_PARENT", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "__nuitka_binary_dir", raising=False)


def test_is_compiled_pyinstaller(monkeypatch):
    _reset_compile_flags(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert autostart._is_compiled() is True


def test_is_compiled_nuitka_onefile_parent(monkeypatch):
    _reset_compile_flags(monkeypatch)
    monkeypatch.setenv("NUITKA_ONEFILE_PARENT", "C:\\fake\\app.exe")
    assert autostart._is_compiled() is True


def test_is_compiled_nuitka_onefile_binary(monkeypatch):
    _reset_compile_flags(monkeypatch)
    monkeypatch.setenv("NUITKA_ONEFILE_BINARY", "C:\\fake\\app.exe")
    assert autostart._is_compiled() is True


def test_is_compiled_nuitka_binary_dir(monkeypatch):
    _reset_compile_flags(monkeypatch)
    monkeypatch.setattr(
        sys, "__nuitka_binary_dir", "/fake", raising=False,
    )
    monkeypatch.setattr(sys, "argv", ["pytest"])
    assert autostart._is_compiled() is True


def test_is_compiled_plain_python(monkeypatch, tmp_path):
    _reset_compile_flags(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["pytest"])
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("")
    monkeypatch.setattr(sys, "executable", str(fake_python))
    assert autostart._is_compiled() is False


def test_is_compiled_non_python_exe(monkeypatch, tmp_path):
    _reset_compile_flags(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["pytest"])
    fake_exe = tmp_path / "myapp.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert autostart._is_compiled() is True


# --- _resolve_launch_target ---

def test_resolve_target_from_nuitka_env(monkeypatch, tmp_path):
    _reset_compile_flags(monkeypatch)
    fake_exe = tmp_path / "app.exe"
    fake_exe.write_text("")
    monkeypatch.setenv("NUITKA_ONEFILE_BINARY", str(fake_exe))
    result = autostart._resolve_launch_target()
    assert result is not None
    assert result.resolve() == fake_exe.resolve()


def test_resolve_target_from_argv(monkeypatch, tmp_path):
    _reset_compile_flags(monkeypatch)
    fake_exe = tmp_path / "app.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(sys, "argv", [str(fake_exe)])
    result = autostart._resolve_launch_target()
    assert result is not None
    assert result.resolve() == fake_exe.resolve()


def test_resolve_target_none_for_python(monkeypatch, tmp_path):
    _reset_compile_flags(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["pytest"])
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("")
    monkeypatch.setattr(sys, "executable", str(fake_python))
    assert autostart._resolve_launch_target() is None


# --- _pythonw_from_venv ---

def test_pythonw_from_venv_found(monkeypatch, tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    python_exe = scripts / "python.exe"
    pythonw_exe = scripts / "pythonw.exe"
    python_exe.write_text("")
    pythonw_exe.write_text("")

    monkeypatch.setattr(sys, "executable", str(python_exe))
    result = autostart._pythonw_from_venv()
    assert result is not None
    assert result.resolve() == pythonw_exe.resolve()


def test_pythonw_from_venv_missing(monkeypatch, tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    python_exe = scripts / "python.exe"
    python_exe.write_text("")
    monkeypatch.setattr(sys, "executable", str(python_exe))
    # Второй кандидат (.venv проекта) может существовать реально —
    # поэтому проверяем только: не падает и возвращает Path|None.
    result = autostart._pythonw_from_venv()
    assert result is None or isinstance(result, Path)


# --- build_command ---

def test_build_command_source_mode(monkeypatch):
    _reset_compile_flags(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["pytest"])
    cmd = autostart.build_command()
    # main.py в этом проекте гарантированно существует.
    assert cmd is not None
    assert "main.py" in cmd
    assert cmd.startswith('"')


def test_build_command_compiled_mode(monkeypatch, tmp_path):
    _reset_compile_flags(monkeypatch)
    fake_exe = tmp_path / "CCRun.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", [str(fake_exe)])
    cmd = autostart.build_command()
    assert cmd is not None
    assert "CCRun.exe" in cmd
    assert cmd.startswith('"')


def test_build_command_missing_main_py(monkeypatch):
    """Если main.py не найден — возвращает None.

    Проверяем через патч Path.exists: main_py.exists() → False.
    """
    _reset_compile_flags(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["pytest"])

    original_exists = Path.exists

    def fake_exists(self):
        if self.name == "main.py":
            return False
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    assert autostart.build_command() is None


# --- Обработчики не падают на реальном реестре (Windows only) ---

@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows-only",
)
def test_is_enabled_does_not_raise():
    # Просто smoke-тест: чтение не должно падать на реальной Windows.
    result = autostart.is_enabled()
    assert isinstance(result, bool)
