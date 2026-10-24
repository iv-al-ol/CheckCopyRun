"""Исключения сервисов копирования и восстановления.

Вынесены отдельно, чтобы copy_service и restore_service могли
ссылаться на них без циклических импортов.
"""

from __future__ import annotations


class CopyError(RuntimeError):
    """Базовая ошибка копирования/восстановления."""


class CopyValidationError(CopyError):
    """Параметры копирования не прошли проверку."""
