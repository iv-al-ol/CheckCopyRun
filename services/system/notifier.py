"""Показ уведомлений: интерфейс провайдеров и сервисные фолбэки.

Собственное всплывающее окно с плавным появлением и исчезновением
живёт в UI-слое (`ui/components/toast.py`): только Tk умеет
анимировать и удерживать уведомление произвольное время. Этот
модуль предоставляет:

  • протокол `Notifier` и чистые функции форматирования текста;
  • `TrayNotifier` — balloon иконки трея (`pystray`), фолбэк,
    если UI-тост недоступен;
  • `NullNotifier` — тихий no-op.

Показ идёт из фонового потока мониторинга, поэтому все
провайдеры обязаны быть потокобезопасными. Форматирование
вынесено в чистые функции — их легко тестировать без Tk.

Заголовки уведомлений начинаются с `APP_NAME`, чтобы
пользователь сразу видел, откуда пришло уведомление.

Для одиночного уведомления об изменениях текст идёт списком
(без суммирования файлов):
    Добавлено: 2
    Изменено: 1
    Удалено: 3
Нулевые категории опускаются.

В заголовке агрегированного уведомления нет числа и падежа —
только «Обновления в профилях», а список профилей уходит в
тело. Это избавляет от ошибок склонения («в 2 профиля»).

`Notification.open_path` — необязательный путь к файлу, который
можно открыть из уведомления (кнопка «Открыть» в тосте). Для
одиночного уведомления о сообщении источника это путь к
`!CCRun/message.txt`. Для агрегата и split-summary путь пустой:
некуда вести пользователя из одного уведомления про несколько
профилей.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from config.constants import (
    APP_NAME,
    NOTIFY_AGGREGATE_MAX_ITEMS,
)
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "ChainNotifier",
    "Notification",
    "Notifier",
    "NullNotifier",
    "ProfileDigest",
    "TrayNotifier",
    "build_fallback_notifier",
    "format_changes_summary",
    "format_profile_notification",
    "format_split_summary",
    "plural_files",
    "plural_profiles",
]


@dataclass
class Notification:
    """Готовое уведомление: заголовок и тело."""

    title: str
    body: str

    # Секунды до автоскрытия; 0 — не скрывать автоматически.
    auto_close_sec: int = 0

    # Путь к файлу для кнопки «Открыть». Пустая строка — кнопки
    # нет. Заполняется только там, где это имеет смысл (одно
    # уведомление, известен конкретный файл).
    open_path: str = ""


class Notifier(Protocol):
    """Интерфейс показа уведомлений."""

    def notify(self, notification: Notification) -> bool:
        """Показывает уведомление. `True` — показано."""
        ...


class NullNotifier:
    """Заглушка: уведомления отключены или недоступны."""

    def notify(self, notification: Notification) -> bool:
        logger.debug(
            "NullNotifier: %r / %r", notification.title, notification.body,
        )
        return False


class TrayNotifier:
    """Balloon через иконку трея."""

    def __init__(self, tray_manager: object) -> None:
        self._tray = tray_manager

    def notify(self, notification: Notification) -> bool:
        notify = getattr(self._tray, "notify", None)
        if not callable(notify):
            return False
        try:
            return bool(
                notify(notification.body, notification.title),
            )
        except Exception as exc:
            logger.error(
                "TrayNotifier: ошибка показа: %r", exc, exc_info=True,
            )
            return False


class ChainNotifier:
    """Пробует провайдеры по очереди до первого успеха."""

    def __init__(self, providers: Sequence[Notifier]) -> None:
        self._providers = list(providers)

    def notify(self, notification: Notification) -> bool:
        for provider in self._providers:
            try:
                if provider.notify(notification):
                    return True
            except Exception as exc:
                logger.error(
                    "ChainNotifier: провайдер %r упал: %r",
                    type(provider).__name__, exc, exc_info=True,
                )
        return False


def build_fallback_notifier(tray_manager: object) -> Notifier:
    """Цепочка на случай недоступности UI-тоста: трей → no-op."""
    return ChainNotifier([
        TrayNotifier(tray_manager),
        NullNotifier(),
    ])


# --- Форматирование (чистые функции) ---

def plural_files(n: int) -> str:
    """Слово «файл» в правильном падеже."""
    if n % 10 == 1 and n % 100 != 11:
        return "файл"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "файла"
    return "файлов"


def plural_profiles(n: int) -> str:
    """Слово «профиль» в правильном падеже."""
    if n % 10 == 1 and n % 100 != 11:
        return "профиль"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "профиля"
    return "профилей"


def format_changes_summary(
    added: int, modified: int, removed: int,
) -> str:
    """Сводка изменений одной строкой: «добавлено 2, изменено 1, удалено 3».

    Нулевые компоненты опускаются, чтобы текст не шумел.
    Без суммирования в конце: число в каждой категории и так
    даёт полную картину, а общий итог дублирует его и выглядит
    избыточно («Удалено 2 — 2 файла»).
    """
    parts: list[str] = []
    if added:
        parts.append(f"добавлено {added}")
    if modified:
        parts.append(f"изменено {modified}")
    if removed:
        parts.append(f"удалено {removed}")
    return ", ".join(parts)


@dataclass
class ProfileDigest:
    """Что произошло в одном профиле за цикл опроса."""

    profile_name: str
    added: int = 0
    modified: int = 0
    removed: int = 0
    message_preview: str = ""
    message_truncated: bool = False

    # Путь к `!CCRun/message.txt` этого профиля. Используется
    # для кнопки «Открыть» в тосте одиночного уведомления.
    # Пустая строка — уведомление не про сообщение (или путь
    # неизвестен).
    message_file_path: str = ""

    details: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return (self.added + self.modified + self.removed) > 0

    @property
    def has_message(self) -> bool:
        return bool(self.message_preview)


def format_profile_notification(
    digests: Sequence[ProfileDigest],
    *,
    aggregate: bool = True,
) -> Notification | None:
    """Собирает одно уведомление из набора профилей.

    Один профиль — заголовок с его именем. Несколько и
    `aggregate=True` — одно уведомление со списком (не больше
    `NOTIFY_AGGREGATE_MAX_ITEMS` строк и «…и ещё N»).

    Args:
        digests: Данные по профилям с непустыми изменениями.
        aggregate: Склеивать ли профили в одно уведомление.

    Returns:
        `Notification` или `None`, если показывать нечего.
    """
    items = [
        d for d in digests
        if d.has_changes or d.has_message
    ]
    if not items:
        return None

    if len(items) == 1 or not aggregate:
        return _single_notification(items[0])

    return _aggregated_notification(items)


def _single_notification(digest: ProfileDigest) -> Notification:
    body_parts: list[str] = []

    if digest.has_changes:
        lines: list[str] = []
        if digest.added:
            lines.append(f"Добавлено: {digest.added}")
        if digest.modified:
            lines.append(f"Изменено: {digest.modified}")
        if digest.removed:
            lines.append(f"Удалено: {digest.removed}")
        body_parts.append("\n".join(lines))

    if digest.has_message:
        message = digest.message_preview
        if digest.message_truncated:
            message += " (сообщение обрезано)"
        body_parts.append(f"Сообщение: {message}")

    body = "\n".join(body_parts) or "Есть обновления."

    # Кнопка «Открыть» — только если уведомление содержит
    # сообщение и путь к файлу известен. Иначе открывать нечего.
    open_path = ""
    if digest.has_message and digest.message_file_path:
        open_path = digest.message_file_path

    return Notification(
        title=f"{APP_NAME}: {digest.profile_name}",
        body=body,
        open_path=open_path,
    )


def _aggregated_notification(
    items: Sequence[ProfileDigest],
) -> Notification:
    lines: list[str] = []

    for digest in items[:NOTIFY_AGGREGATE_MAX_ITEMS]:
        lines.append(_digest_line(digest))

    hidden = len(items) - NOTIFY_AGGREGATE_MAX_ITEMS
    if hidden > 0:
        lines.append(
            f"…и ещё {hidden} {plural_profiles(hidden)}",
        )

    # Кнопки «Открыть» нет: уведомление про несколько
    # профилей, вести пользователя к одному файлу нельзя.
    return Notification(
        title=f"{APP_NAME}: Обновления в профилях",
        body="\n".join(lines),
    )


def format_split_summary(extra_count: int) -> Notification:
    """Обобщённое уведомление для split-режима (4-й тост).

    Показывается, когда подробных тостов уже
    `NOTIFY_SPLIT_MAX_DETAILED`, а профилей с новостями больше.
    Пользователь видит «есть ещё обновления, проверьте папки
    источников» — без деталей и без риска, что новые тосты
    не поместятся в лимит.
    """
    title = f"{APP_NAME}: Есть обновления"
    if extra_count <= 0:
        return Notification(
            title=title,
            body="Проверьте папки источников.",
        )
    return Notification(
        title=title,
        body=(
            f"Ещё в {extra_count} {plural_profiles(extra_count)} "
            f"есть обновления. Проверьте папки источников."
        ),
    )


def _digest_line(digest: ProfileDigest) -> str:
    parts: list[str] = []
    if digest.has_changes:
        parts.append(
            format_changes_summary(
                digest.added, digest.modified, digest.removed,
            ),
        )
    if digest.has_message:
        parts.append("есть сообщение")
    suffix = f" — {', '.join(parts)}" if parts else ""
    return f"• {digest.profile_name}{suffix}"
