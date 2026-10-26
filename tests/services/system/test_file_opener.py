"""Тесты fallback-цепочки открытия файла.

`os.startfile` и `subprocess.Popen` подменяются через
monkeypatch: реальные окна в тестах не открываем.
"""

from __future__ import annotations

import os
import subprocess

from services.system.file_opener import (
    METHOD_ASSOC,
    METHOD_EXPLORER,
    METHOD_NOTEPAD,
    open_file_with_fallback,
    try_open_associated,
)


def _make_file(tmp_path):
    f = tmp_path / "message.txt"
    f.write_text("hello", encoding="utf-8")
    return f


def _patch_startfile(monkeypatch, behavior):
    """behavior: callable(path) или исключение."""
    def fake(path):
        if isinstance(behavior, Exception):
            raise behavior
        return behavior(path)
    monkeypatch.setattr(
        os, "startfile", fake, raising=False,
    )


def _patch_startfile_missing(monkeypatch):
    """Имитирует отсутствие os.startfile (не-Windows)."""
    monkeypatch.delattr(os, "startfile", raising=False)


class _RecordingPopen:
    """Записывает вызовы и ничего не запускает."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        return object()


def _patch_popen(monkeypatch, behavior=None):
    """behavior: None (успех) | Exception (падение)."""
    recorder = _RecordingPopen()

    def fake(args, **kwargs):
        if isinstance(behavior, Exception):
            raise behavior
        return recorder(args, **kwargs)

    monkeypatch.setattr(
        subprocess, "Popen", fake, raising=True,
    )
    return recorder


# --- Успех ---

def test_open_success_via_assoc(monkeypatch, tmp_path):
    f = _make_file(tmp_path)
    called: list[str] = []
    _patch_startfile(monkeypatch, lambda p: called.append(p))

    result = open_file_with_fallback(str(f))

    assert result.success is True
    assert result.method == METHOD_ASSOC
    assert called == [str(f)]


# --- Ассоциация падает → Блокнот ---

def test_open_falls_back_to_notepad(monkeypatch, tmp_path):
    f = _make_file(tmp_path)
    _patch_startfile(monkeypatch, OSError(1155, "no assoc"))
    popen = _patch_popen(monkeypatch)

    result = open_file_with_fallback(str(f))

    assert result.success is True
    assert result.method == METHOD_NOTEPAD
    assert len(popen.calls) == 1
    assert popen.calls[0][0] == "notepad.exe"
    assert popen.calls[0][1] == str(f)


def test_open_without_startfile_uses_notepad(monkeypatch, tmp_path):
    """Не-Windows или os.startfile удалён — сразу Блокнот."""
    f = _make_file(tmp_path)
    _patch_startfile_missing(monkeypatch)
    popen = _patch_popen(monkeypatch)

    result = open_file_with_fallback(str(f))

    assert result.success is True
    assert result.method == METHOD_NOTEPAD
    assert popen.calls[0][0] == "notepad.exe"


# --- Блокнот падает → Проводник ---

def test_open_falls_back_to_explorer(monkeypatch, tmp_path):
    f = _make_file(tmp_path)
    _patch_startfile(monkeypatch, OSError(1155, "no assoc"))

    calls: list[list[str]] = []

    def fake(args, **kwargs):
        calls.append(list(args))
        # Первый вызов — notepad.exe (падает),
        # второй — explorer (успех).
        if args[0] == "notepad.exe":
            raise OSError("notepad broken")
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake)

    result = open_file_with_fallback(str(f))

    assert result.success is True
    assert result.method == METHOD_EXPLORER
    assert calls[0][0] == "notepad.exe"
    assert calls[1][0] == "explorer"
    assert calls[1][1] == f"/select,{f}"


# --- Всё падает ---

def test_open_all_methods_fail(monkeypatch, tmp_path):
    f = _make_file(tmp_path)
    _patch_startfile(monkeypatch, OSError(1155, "no assoc"))

    def fake(args, **kwargs):
        raise OSError("nope")

    monkeypatch.setattr(subprocess, "Popen", fake)

    result = open_file_with_fallback(str(f))

    assert result.success is False
    assert result.method == ""
    assert str(f) in result.error
    assert "Не удалось открыть" in result.error


# --- Файл не существует ---

def test_open_missing_file(tmp_path):
    missing = tmp_path / "gone.txt"

    result = open_file_with_fallback(str(missing))

    assert result.success is False
    assert "не найден" in result.error.lower()
    assert str(missing) in result.error


def test_open_empty_path():
    result = open_file_with_fallback("")

    assert result.success is False
    assert "не задан" in result.error.lower()


# --- Проверка, что isfile проверяется до запуска ---

def test_missing_file_does_not_call_startfile(
    monkeypatch, tmp_path,
):
    missing = tmp_path / "gone.txt"
    called: list[str] = []
    _patch_startfile(monkeypatch, lambda p: called.append(p))

    result = open_file_with_fallback(str(missing))

    assert result.success is False
    assert called == []


# --- try_open_associated: только ассоциация, без подмены ---

def test_associated_success(monkeypatch, tmp_path):
    f = _make_file(tmp_path)
    called: list[str] = []
    _patch_startfile(monkeypatch, lambda p: called.append(p))

    result = try_open_associated(str(f))

    assert result.success is True
    assert result.method == METHOD_ASSOC
    assert called == [str(f)]


def test_associated_missing_association(monkeypatch, tmp_path):
    """Нет ассоциации — отказ, без Блокнота и Проводника."""
    f = _make_file(tmp_path)
    _patch_startfile(monkeypatch, OSError(1155, "no assoc"))
    popen = _patch_popen(monkeypatch)

    result = try_open_associated(str(f))

    assert result.success is False
    assert "связанной" in result.error
    assert popen.calls == []


def test_associated_empty_path():
    result = try_open_associated("")

    assert result.success is False
    assert "не задан" in result.error.lower()


def test_associated_missing_file(tmp_path):
    missing = tmp_path / "gone.md"

    result = try_open_associated(str(missing))

    assert result.success is False
    assert "не найден" in result.error.lower()


def test_associated_without_startfile(monkeypatch, tmp_path):
    f = _make_file(tmp_path)
    _patch_startfile_missing(monkeypatch)

    result = try_open_associated(str(f))

    assert result.success is False
    assert "недоступны" in result.error.lower()
