"""Общие фикстуры для тестов."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from services.copy_service import CopyService


@pytest.fixture
def src(tmp_path: Path) -> Path:
    d = tmp_path / "src"
    d.mkdir()
    return d


@pytest.fixture
def dst(tmp_path: Path) -> Path:
    d = tmp_path / "dst"
    d.mkdir()
    return d


@pytest.fixture
def run_copy():
    """Запускает CopyService и дожидается завершения.

    Возвращает функцию:

        run_copy(src, dst, *, create_backup=True,
                 cancel_after=None, timeout=10.0) -> CopyResult

    • create_backup — передаётся в сервис;
    • cancel_after  — если задан, cancel() вызывается сразу
                       после обработки файла с номером processed
                       >= cancel_after. Это детерминированный
                       способ отменить «на середине».
    • timeout       — защита от зависания в тестах.
    """
    def _run(
        src: Path,
        dst: Path,
        *,
        create_backup: bool = True,
        cancel_after: int | None = None,
        timeout: float = 10.0,
    ):
        svc = CopyService(scheduler=lambda fn: fn())
        done = threading.Event()
        results = []
        errors = []

        def on_progress(p):
            if cancel_after is not None and p.processed >= cancel_after:
                svc.cancel()

        started = svc.start(
            source=str(src),
            destination=str(dst),
            create_backup=create_backup,
            on_progress=on_progress,
            on_done=lambda r: (results.append(r), done.set()),
            on_error=errors.append,
        )
        assert started, "CopyService.start вернул False"
        assert done.wait(timeout=timeout), (
            f"Копирование не завершилось за {timeout} с"
        )
        assert errors == [], f"Ошибки: {errors}"
        assert len(results) == 1, "on_done не вызван ровно один раз"
        return results[0]

    return _run
