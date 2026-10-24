"""Общие фикстуры для тестов."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from services.copy.copy_service import PHASE_COPY, CopyService
from services.restore.restore_service import RestoreService


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
                 cancel_after=None, mirror=False, timeout=10.0)
        -> CopyResult

    • create_backup — передаётся в сервис;
    • cancel_after  — cancel() вызывается, когда обработано
                       >= N файлов. Учитываются только события
                       фазы "copy": фаза "save_state" приходит
                       с processed=total и не должна триггерить
                       отмену;
    • mirror        — режим зеркала;
    • timeout       — защита от зависания в тестах.
    """
    def _run(
        src: Path,
        dst: Path,
        *,
        create_backup: bool = True,
        cancel_after: int | None = None,
        mirror: bool = False,
        timeout: float = 10.0,
    ):
        svc = CopyService(scheduler=lambda fn: fn())
        done = threading.Event()
        results = []
        errors = []

        def on_progress(p):
            # Отмена — только по прогрессу копирования файлов.
            # Фазы save_state приходят с processed=total; их
            # нельзя считать «обработано N файлов».
            if p.phase != PHASE_COPY:
                return
            if (
                cancel_after is not None
                and p.processed >= cancel_after
            ):
                svc.cancel()

        started = svc.start(
            source=str(src),
            destination=str(dst),
            create_backup=create_backup,
            mirror_mode=mirror,
            on_progress=on_progress,
            on_done=lambda r: (results.append(r), done.set()),
            on_error=errors.append,
        )
        assert started, "CopyService.start вернул False"
        assert done.wait(timeout=timeout), (
            f"Копирование не завершилось за {timeout} с"
        )
        assert errors == [], f"Ошибки: {errors}"
        assert len(results) == 1, (
            "on_done не вызван ровно один раз"
        )
        return results[0]

    return _run


@pytest.fixture
def run_restore():
    """Запускает RestoreService и дожидается завершения.

    Возвращает функцию:

        run_restore(state_ref, dst, *, cancel_after=None,
                    timeout=10.0) -> RestoreResult
    """
    def _run(
        state_ref: str | Path,
        dst: Path,
        *,
        cancel_after: int | None = None,
        timeout: float = 10.0,
    ):
        svc = RestoreService(scheduler=lambda fn: fn())
        done = threading.Event()
        results = []
        errors = []

        def on_progress(p):
            if (
                cancel_after is not None
                and p.processed >= cancel_after
            ):
                svc.cancel()

        started = svc.start(
            backup_state_ref=str(state_ref),
            destination=str(dst),
            on_progress=on_progress,
            on_done=lambda r: (results.append(r), done.set()),
            on_error=errors.append,
        )
        assert started, "RestoreService.start вернул False"
        assert done.wait(timeout=timeout), (
            f"Восстановление не завершилось за {timeout} с"
        )
        assert errors == [], f"Ошибки: {errors}"
        assert len(results) == 1
        return results[0]

    return _run
