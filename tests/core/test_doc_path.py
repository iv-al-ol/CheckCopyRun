"""Тесты поиска README рядом с программой."""

from __future__ import annotations

import sys

from core import paths


def test_finds_readme_in_project_root():
    """В исходниках README лежит в корне проекта."""
    found = paths.get_doc_path("README.md")
    assert found is not None
    assert found.name == "README.md"
    assert found.parent == paths.get_resource_root()


def test_missing_file_returns_none():
    assert paths.get_doc_path("НЕТ_ТАКОГО_ФАЙЛА.md") is None


def test_prefers_exe_directory(monkeypatch, tmp_path):
    """Рядом с .exe найденный файл важнее корня проекта."""
    readme = tmp_path / "README.md"
    readme.write_text("# из exe", encoding="utf-8")

    fake_exe = tmp_path / "CCRun.exe"
    fake_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    found = paths.get_doc_path("README.md")
    assert found == readme


def test_falls_back_when_exe_dir_empty(monkeypatch, tmp_path):
    """Если рядом с .exe файла нет — берётся корень проекта."""
    fake_exe = tmp_path / "CCRun.exe"
    fake_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    found = paths.get_doc_path("README.md")
    assert found is not None
    assert found.parent == paths.get_resource_root()
