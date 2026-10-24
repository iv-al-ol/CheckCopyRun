"""CAS-хранилище содержимого: blob-ы по sha256.

Файл содержимого хранится ровно один раз — сколько бы раз
он ни встречался в разных состояниях. Имя файла = полный
sha256 (64 hex-символа), подкаталог = первые 2 символа, чтобы
не было 100 000 файлов в одной папке.

Структура:
  <destination>/!CCRun/blobs/<ab>/<full_sha256>

Blob-ы неизменяемы после создания. Удаляются только через gc()
по результатам сверки с набором используемых хэшей.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from services.copy_constants import (
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
    "BlobHashMismatch",
    "BlobStore",
]


class BlobError(RuntimeError):
    """Базовая ошибка хранилища blob-ов."""


class BlobHashMismatch(BlobError):
    """Хэш фактического содержимого не совпал с ожидаемым."""


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.debug("Не удалось удалить %s: %r", path, exc)


class BlobStore:
    """Хранилище уникальных файлов по sha256."""

    def __init__(self, destination: str | Path):
        self._root = (
            Path(destination) / CCRUN_DIR_NAME / BLOBS_DIR_NAME
        )
        try:
            self._root.mkdir(parents=True, exist_ok=True)
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
        return self.path_for(sha256).is_file()

    def get(self, sha256: str) -> Path | None:
        """Путь к blob-у или None."""
        if not _is_sha256(sha256):
            return None
        p = self.path_for(sha256)
        return p if p.is_file() else None

    def put(
        self,
        src_path: str | Path,
        sha256: str,
    ) -> bool:
        """Копирует файл в pool. Возвращает True, если blob новый.

        Содержимое верифицируется по sha256 во время копирования.
        Если уже есть blob с таким хэшем — ничего не делает
        и возвращает False.
        """
        if not _is_sha256(sha256):
            raise BlobHashMismatch(
                f"Некорректный sha256: {sha256!r}"
            )

        target = self.path_for(sha256)
        if target.is_file():
            return False

        target_dir = target.parent
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BlobError(
                f"Не удалось создать {target_dir}: {exc}"
            ) from exc

        tmp = Path(str(target) + TMP_SUFFIX)
        _safe_unlink(tmp)

        h = hashlib.new(BLOB_HASH_ALGORITHM)
        try:
            with open(src_path, "rb") as src, open(
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
            raise BlobHashMismatch(
                f"Хэш {src_path} не совпал: "
                f"ожидался {sha256}, получен {actual}"
            )

        try:
            os.replace(str(tmp), str(target))
        except OSError as exc:
            _safe_unlink(tmp)
            raise BlobError(
                f"Не удалось зафиксировать {target}: {exc}"
            ) from exc

        logger.debug(
            "Добавлен blob: %s (%d байт)",
            sha256[:12], target.stat().st_size,
        )
        return True

    def iter_all(self) -> Iterator[tuple[str, Path]]:
        """Все blob-ы: (sha256, path)."""
        for sub in self._root.iterdir():
            if not sub.is_dir():
                continue
            for blob in sub.iterdir():
                if not blob.is_file():
                    continue
                if blob.name.endswith(TMP_SUFFIX):
                    continue
                if not _is_sha256(blob.name):
                    continue
                yield blob.name, blob

    def stats(self) -> tuple[int, int]:
        """(количество blob-ов, суммарный размер в байтах)."""
        count = 0
        total = 0
        for _, p in self.iter_all():
            try:
                total += p.stat().st_size
                count += 1
            except OSError:
                continue
        return count, total

    def gc(self, keep: Iterable[str]) -> tuple[int, int]:
        """Удаляет blob-ы, не входящие в keep.

        Возвращает (удалено файлов, освобождено байт).
        Пустые подкаталоги тоже убираются.
        """
        keep_set = set(keep)
        deleted = 0
        bytes_freed = 0

        for sub in list(self._root.iterdir()):
            if not sub.is_dir():
                continue

            for blob in list(sub.iterdir()):
                if not blob.is_file():
                    continue
                if blob.name.endswith(TMP_SUFFIX):
                    _safe_unlink(blob)
                    continue
                if blob.name in keep_set:
                    continue
                try:
                    size = blob.stat().st_size
                    blob.unlink()
                    deleted += 1
                    bytes_freed += size
                    logger.debug(
                        "GC: удалён blob %s (%d байт)",
                        blob.name[:12], size,
                    )
                except OSError as exc:
                    logger.warning(
                        "GC: не удалось удалить %s: %r",
                        blob, exc,
                    )

            try:
                if not any(sub.iterdir()):
                    sub.rmdir()
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
