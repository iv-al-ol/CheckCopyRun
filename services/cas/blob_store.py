"""CAS-хранилище содержимого: blob-ы по sha256.

Файл содержимого хранится ровно один раз — сколько бы раз
он ни встречался в разных состояниях. Имя файла = полный
sha256 (64 hex-символа), подкаталог = первые 2 символа, чтобы
не было 100 000 файлов в одной папке.

Структура:
  <destination>/!CCRun/blobs/<ab>/<full_sha256>

Blob-ы неизменяемы после создания. Удаляются только через gc()
по результатам сверки с набором используемых хэшей.

Поддержка длинных путей Windows: все I/O через long_io.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from pathlib import Path

from core import long_io
from core.paths import to_long_path
from services.common.copy_constants import (
    BLOB_CHUNK_SIZE,
    BLOB_HASH_ALGORITHM,
    BLOB_SUBDIR_LEN,
    BLOBS_DIR_NAME,
    CCRUN_DIR_NAME,
    TMP_SUFFIX,
)
from utils.logger import get_logger

logger = get_logger(__name__)


__all__ = [
    "BlobError",
    "BlobHashMismatchError",
    "BlobStore",
]


class BlobError(RuntimeError):
    """Базовая ошибка хранилища blob-ов."""


class BlobHashMismatchError(BlobError):
    """Хэш фактического содержимого не совпал с ожидаемым."""


def _safe_unlink(path: str) -> None:
    try:
        if long_io.exists(path):
            long_io.remove(path)
    except OSError as exc:
        logger.debug("Не удалось удалить %s: %r", path, exc)


class BlobStore:
    """Хранилище уникальных файлов по sha256."""

    def __init__(self, destination: str | Path) -> None:
        raw = (
            Path(destination) / CCRUN_DIR_NAME / BLOBS_DIR_NAME
        )
        self._root = Path(to_long_path(str(raw)))
        try:
            long_io.makedirs(str(self._root), exist_ok=True)
        except OSError as exc:
            raise BlobError(
                f"Не удалось создать {self._root}: {exc}"
            ) from exc

    # --- Публичное ---

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, sha256: str) -> Path:
        return self._root / sha256[:BLOB_SUBDIR_LEN] / sha256

    def has(self, sha256: str) -> bool:
        if not _is_sha256(sha256):
            return False
        return long_io.isfile(
            str(self.path_for(sha256)),
        )

    def get(self, sha256: str) -> Path | None:
        """Путь к blob-у или None."""
        if not _is_sha256(sha256):
            return None
        p = self.path_for(sha256)
        return p if long_io.isfile(str(p)) else None

    def put(
        self,
        src_path: str | Path,
        sha256: str,
    ) -> bool:
        """Копирует файл в pool. Возвращает True, если blob новый."""
        if not _is_sha256(sha256):
            raise BlobHashMismatchError(
                f"Некорректный sha256: {sha256!r}"
            )

        target = self.path_for(sha256)
        if long_io.isfile(str(target)):
            return False

        try:
            long_io.makedirs(
                str(target.parent), exist_ok=True,
            )
        except OSError as exc:
            raise BlobError(
                f"Не удалось создать {target.parent}: {exc}"
            ) from exc

        tmp = str(target) + TMP_SUFFIX
        _safe_unlink(tmp)

        h = hashlib.new(BLOB_HASH_ALGORITHM)
        try:
            with long_io.open(src_path, "rb") as src, long_io.open(
                tmp, "wb",
            ) as dst:
                while True:
                    chunk = src.read(BLOB_CHUNK_SIZE)
                    if not chunk:
                        break
                    h.update(chunk)
                    dst.write(chunk)
        except OSError as exc:
            _safe_unlink(tmp)
            raise BlobError(
                f"Не удалось скопировать {src_path}: {exc}"
            ) from exc

        actual = h.hexdigest()
        if actual != sha256:
            _safe_unlink(tmp)
            raise BlobHashMismatchError(
                f"Хэш {src_path} не совпал: "
                f"ожидался {sha256}, получен {actual}"
            )

        try:
            long_io.replace(tmp, str(target))
        except OSError as exc:
            _safe_unlink(tmp)
            raise BlobError(
                f"Не удалось зафиксировать {target}: {exc}"
            ) from exc

        logger.debug(
            "Добавлен blob: %s (%d байт)",
            sha256[:12], long_io.getsize(str(target)),
        )
        return True

    def iter_all(self) -> Iterator[tuple[str, Path]]:
        """Все blob-ы: (sha256, path)."""
        for sub in long_io.scandir(str(self._root)):
            if not sub.is_dir():
                continue
            for blob in long_io.scandir(sub.path):
                if not blob.is_file():
                    continue
                if blob.name.endswith(TMP_SUFFIX):
                    continue
                if not _is_sha256(blob.name):
                    continue
                yield blob.name, Path(blob.path)

    def stats(self) -> tuple[int, int]:
        """(количество blob-ов, суммарный размер в байтах)."""
        count = 0
        total = 0
        for _, p in self.iter_all():
            try:
                total += long_io.getsize(str(p))
                count += 1
            except OSError:
                continue
        return count, total

    def gc(self, keep: Iterable[str]) -> tuple[int, int]:
        """Удаляет blob-ы, не входящие в keep."""
        keep_set = set(keep)
        deleted = 0
        bytes_freed = 0

        for sub in list(long_io.scandir(str(self._root))):
            if not sub.is_dir():
                continue

            for blob in list(long_io.scandir(sub.path)):
                if not blob.is_file():
                    continue
                if blob.name.endswith(TMP_SUFFIX):
                    _safe_unlink(blob.path)
                    continue
                if blob.name in keep_set:
                    continue
                try:
                    size = long_io.getsize(blob.path)
                    long_io.remove(blob.path)
                    deleted += 1
                    bytes_freed += size
                    logger.debug(
                        "GC: удалён blob %s (%d байт)",
                        blob.name[:12], size,
                    )
                except OSError as exc:
                    logger.warning(
                        "GC: не удалось удалить %s: %r",
                        blob.path, exc,
                    )

            try:
                if not long_io.listdir(sub.path):
                    long_io.rmdir(sub.path)
            except OSError:
                pass

        if deleted:
            logger.info(
                "GC blob-ов: удалено %d файлов, %d байт",
                deleted, bytes_freed,
            )
        return deleted, bytes_freed

    def clear(self) -> tuple[int, int]:
        """Удаляет все blob-ы. Использовать с осторожностью."""
        return self.gc(keep=set())


# --- Вспомогательное ---

def _is_sha256(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if len(s) != 64:
        return False
    try:
        int(s, 16)
    except ValueError:
        return False
    return True
