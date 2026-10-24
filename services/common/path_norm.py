"""Нормализация путей внутри состояний CAS.

Пути в `state_*.json` всегда хранятся с прямыми слэшами, чтобы
сравнение работало независимо от разделителя ОС. Раньше функция
дублировалась в `cas/destination_state.py`, `restore/restore_apply.py`
и `restore/restore_planner.py`.
"""

from __future__ import annotations


def norm_path(path: str) -> str:
    """Приводит путь к виду с прямыми слэшами."""
    return path.replace("\\", "/")
