"""Общая часть фоновых воркеров copy и restore.

`_CopyWorker` и `_RestoreWorker` — разные потоки с разной
логикой, но отправка событий в UI у них одинаковая: любая
ошибка планировщика не должна убивать воркер. Раньше
`_emit_done`, `_emit_error` и `_safe_schedule` дублировались
в двух файлах.
"""

from __future__ import annotations

from collections.abc import Callable

from utils.logger import get_logger

logger = get_logger(__name__)


class WorkerEventsMixin:
    """Безопасная доставка событий из фонового потока в UI.

    Наследник должен задать атрибуты `_schedule`, `_on_done`,
    `_on_error` и `_result`.
    """

    _schedule: Callable[[Callable[[], None]], None]
    _on_done: Callable[[object], None]
    _on_error: Callable[[str], None]
    _result: object

    def _emit_done(self) -> None:
        self._safe_schedule(
            lambda r=self._result: self._on_done(r),
            "on_done",
        )

    def _emit_error(self, message: str) -> None:
        self._safe_schedule(
            lambda m=message: self._on_error(m),
            "on_error",
        )

    def _safe_schedule(
        self, callback: Callable[[], None], name: str,
    ) -> None:
        try:
            self._schedule(callback)
        except Exception as exc:
            logger.error(
                "scheduler упал на %s: %r", name, exc,
            )
