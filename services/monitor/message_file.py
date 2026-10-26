"""Сообщение от автора папки-источника: `!CCRun/message.txt`.

Автор источника (например, сборщик) может положить текст в
`<source>/!CCRun/message.txt` — приложение показывает его в
уведомлении. Папка `!CCRun` исключена из копирования, mirror и
сканирования состояний (`is_special_first_segment`), поэтому
файл никогда не попадает в destination и не ломает CAS.

Строки, начинающиеся с `#` (в том числе после ведущих пробелов),
считаются комментариями и в превью не попадают. Так шаблон,
создаваемый кнопкой «Создать message.txt», не показывается
пользователю как сообщение. Если в файле только комментарии
— сообщение пустое, уведомление не показывается.

sha256 считается по **сырым байтам** файла (включая
комментарии): изменение комментария обновляет базу монитора,
но не показывает уведомление. При следующем изменении (уже
с содержимым) sha тоже изменится — уведомление придёт.

Чтение ограничено по размеру: огромный или бинарный файл не
должен ни съедать память, ни ломать уведомление.
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
    "MESSAGE_TEMPLATE",
    "SourceMessage",
    "ensure_message_template",
    "message_path",
    "read_message",
]

# Кодировки в порядке приоритета. UTF-8 (с BOM и без) — норма,
# cp1251 — наследие блокнота на русской Windows.
_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1251")

_ELLIPSIS = "…"

_COMMENT_PREFIX = "#"


# Шаблон, который создаёт кнопка «Создать message.txt».
# Все строки начинаются с `#` — `read_message` их отбросит,
# и пользователь не увидит инструкцию в уведомлении. Текст
# объясняет автору источника, откуда взялась папка !CCRun и
# как оставить сообщение получателю.
MESSAGE_TEMPLATE = """\
# Файл сообщения для CheckCopyRun
#
# Откуда эта папка и этот файл
# ----------------------------
# Кто-то (пользователь программы CheckCopyRun) настроил свою
# копию приложения так, что она следит за вашей папкой как
# за источником: периодически проверяет её на изменения и
# копирует новые файлы в свою папку назначения. Программа
# не вносит никаких изменений в вашу папку — только читает
# её. Папку !CCRun создала именно эта программа: она служит
# «почтовым ящиком» между вами и получателем.
#
# Как оставить сообщение
# ----------------------
# Напишите любой текст ниже разделителя. При следующей
# проверке получатель увидит его в уведомлении рядом с
# информацией о том, какие файлы изменились. Строки,
# начинающиеся с #, считаются комментариями и получателю
# не показываются — этот блок можно не удалять, он не
# попадёт в уведомление.
#
# --- напишите сообщение ниже этой строки ---

"""


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


def ensure_message_template(source: str) -> tuple[bool, str]:
    """Создаёт `!CCRun/message.txt` с шаблоном, если его ещё нет.

    Существующий файл не трогаем: пользователь мог уже написать
    своё сообщение.

    Returns:
        (ok, error_message). Если файл существует или создан
        успешно — `(True, "")`. При ошибке — `(False, текст)`.
    """
    if not source:
        return False, "Не указана папка-источник"

    path = message_path(source)
    if not path:
        return False, "Не указана папка-источник"

    if long_io.isfile(path):
        return True, ""

    target = Path(path)
    try:
        long_io.makedirs(str(target.parent), exist_ok=True)
        with long_io.open(path, "w", encoding="utf-8") as f:
            f.write(MESSAGE_TEMPLATE)
    except OSError as exc:
        logger.warning(
            "ensure_message_template: %s: %r", path, exc,
        )
        return False, f"Ошибка записи {path}: {exc}"

    logger.info("Создан шаблон message.txt: %s", path)
    return True, ""


def read_message(source: str) -> SourceMessage:
    """Читает сообщение источника.

    Возвращает пустой `SourceMessage`, если файла нет, он пуст,
    превышает лимит размера или не читается. Если в файле
    только комментарии (строки с `#`), `text` и `preview`
    пустые, но `sha256` заполнен — чтобы монитор знал, что
    файл прочитан, и не перечитывал его каждый цикл.

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

    sha = hashlib.sha256(raw).hexdigest()

    decoded = _decode(raw)
    text = _strip_comments(decoded)

    if not text.strip():
        # Файл прочитан, но полезного содержимого нет.
        # sha256 отдаём — монитор обновит базу без уведомления.
        return SourceMessage(
            sha256=sha,
            truncated=truncated_file,
        )

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


def _strip_comments(text: str) -> str:
    """Убирает строки, начинающиеся с `#` (в том числе после
    ведущих пробелов). Внутри строки `#` не считается
    комментарием — «Сборка #42 готова» остаётся как есть.
    """
    if not text:
        return ""
    kept = [
        line for line in text.splitlines()
        if not line.lstrip().startswith(_COMMENT_PREFIX)
    ]
    return "\n".join(kept)


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
