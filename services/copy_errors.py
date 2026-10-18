"""Исключения сервиса копирования.

Вынесены отдельно, чтобы copy_backup и copy_service могли
ссылаться на них без циклических импортов.
"""

from __future__ import annotations


class CopyError(RuntimeError):
    """Базовая ошибка копирования."""


class CopyValidationError(CopyError):
    """Параметры не прошли проверку."""


class BackupVerificationError(CopyError):
    """Скопированный бэкап не совпал с оригиналом."""
