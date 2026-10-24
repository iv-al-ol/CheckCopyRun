"""Сообщение от автора папки-источника: `!CCRun/message.txt`.

Автор источника (например, сборщик) может положить текст в
`<source>/!CCRun/message.txt` — приложение показывает его в
уведомлении. Папка `!CCRun` исключена из копирования, mirror и
сканирования состояний (`is_special_first_segment`), поэтому
файл никогда не попадает в destination и не ломает CAS.

Чтение ограничено по размеру: огромный или бинарный файл не
должен ни съедать память, ни ломать уведомление. Хэш содержимого
используется для дедупликации — одно и то же сообщение не
показывается дважды.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from config.constants import (
    MESSAGE_FILE_MAX_BYTES,
    MESSAGE_PREVIEW_CHARS,
    MESSAGE_PREVIEW_LINES,
)
from core import long_io
from core.paths import to_long_path
from services.common.copy_constants import (
    CCRUN_DIR_NAME,
    MESSAGE_FILE_NAME,
)
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "SourceMessage",
    "message_path",
    "read_message",
]

# Кодировки в порядке приоритета. UTF-8 (с BOM и без) — норма,
# cp1251 — наследие блокнота на русской Windows.
_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1251")

_ELLIPSIS = "…"


@dataclass
class SourceMessage:
    """Прочитанное сообщение источника."""

    text: str = ""
    preview: str = ""
    sha256: str = ""
    truncated: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def message_path(source: str) -> str:
    """Путь к `message.txt` внутри служебной папки источника."""
    if not source:
        return ""
    return str(Path(source) / CCRUN_DIR_NAME / MESSAGE_FILE_NAME)


def read_message(source: str) -> SourceMessage:
    """Читает сообщение источника.

    Возвращает пустой `SourceMessage`, если файла нет, он пуст,
    превышает лимит размера или не читается. Никогда не бросает
    исключений наружу: отсутствие сообщения — это норма.

    Args:
        source: Путь к папке-источнику.

    Returns:
        `SourceMessage` с текстом, превью и sha256 содержимого.
    """
    path = message_path(source)
    if not path:
        return SourceMessage()

    try:
        st = long_io.stat(path)
    except OSError as exc:
        logger.debug("read_message: нет файла %r (%r)", path, exc)
        return SourceMessage()

    if st.st_size <= 0:
        return SourceMessage()

    truncated_file = st.st_size > MESSAGE_FILE_MAX_BYTES
    read_bytes = min(st.st_size, MESSAGE_FILE_MAX_BYTES)

    try:
        with long_io.open(to_long_path(path), "rb") as f:
            raw = f.read(read_bytes)
    except OSError as exc:
        logger.warning("read_message: ошибка чтения %r: %r", path, exc)
        return SourceMessage()

    text = _decode(raw)
    if not text.strip():
        return SourceMessage()

    sha = hashlib.sha256(raw).hexdigest()

    return SourceMessage(
        text=text,
        preview=_make_preview(text),
        sha256=sha,
        truncated=truncated_file,
    )


def _decode(raw: bytes) -> str:
    """Декодирует содержимое, перебирая поддерживаемые кодировки."""
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    logger.debug("read_message: ни одна кодировка не подошла")
    return ""


def _make_preview(text: str) -> str:
    """Короткое превью: несколько первых непустых строк."""
    lines = [line.strip() for line in text.splitlines()]
    meaningful = [line for line in lines if line]
    if not meaningful:
        return ""

    head = meaningful[:MESSAGE_PREVIEW_LINES]
    preview = "\n".join(head)

    has_more_lines = len(meaningful) > len(head)
    if has_more_lines or len(preview) > MESSAGE_PREVIEW_CHARS:
        preview = preview[:MESSAGE_PREVIEW_CHARS].rstrip()
        preview += _ELLIPSIS
    return preview
