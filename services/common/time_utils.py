"""Работа со временем в сервисах.

Единая реализация ISO-метки: раньше `now_iso` дублировалась в
`cas/state_store.py` и `cas/destination_state.py`.
"""

from __future__ import annotations

from datetime import datetime


def now_iso() -> str:
    """Текущее время в ISO 8601 с миллисекундами."""
    return datetime.now().isoformat(timespec="milliseconds")
