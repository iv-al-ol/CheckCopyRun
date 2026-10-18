"""Бэкап заменяемых файлов с проверкой и атомарной заменой.

Порядок для каждого файла:
  1. copy2 в <backup>.tmp
  2. проверка размера и содержимого
     (filecmp.cmp(shallow=False) — побайтово)
  3. os.replace(.tmp → финальный бэкап)

Только после шага 3 файл считается бэкапнутым. Если что-то упало
на шагах 1–2 — в destination оригинал ещё не тронут, .tmp убран.

Имя папки бэкапа: !Backup_ГГГГ.ММ.ДД_ЧЧ.ММ.СС.ммм.
В папке создаётся !CCRun/ для манифеста.
"""

from __future__ import annotations

import filecmp
import os
import shutil
from datetime import datetime
from pathlib import Path

from services.copy_constants import (
    BACKUP_PREFIX,
    CCRUN_DIR_NAME,
    TMP_SUFFIX,
)
from services.copy_errors import BackupVerificationError, CopyError
from services.copy_manifest import ManifestEntry, iso_mtime
from utils.logger import get_logger

logger = get_logger(__name__)


class BackupManager:
    """Управляет одной бэкап-папкой и записями в ней.

    Папка создаётся лениво — при первом вызове backup().
    Если за время работы ни одна замена не случилась, папки нет.
    """

    def __init__(self, destination: str):
        self._destination = destination
        self._backup_dir: Path | None = None
        self._entries: list[ManifestEntry] = []

    # --- Публичное ---

    @property
    def backup_dir(self) -> Path | None:
        return self._backup_dir

    @property
    def entries(self) -> tuple[ManifestEntry, ...]:
        return tuple(self._entries)

    def ensure_dir(self) -> Path:
        """Создаёт !Backup_<stamp>/ и !CCRun/ внутри. Идемпотентно."""
        if self._backup_dir is not None:
            return self._backup_dir

        stamp = datetime.now().strftime("%Y.%m.%d_%H.%M.%S.%f")[:-3]
        name = f"{BACKUP_PREFIX}{stamp}"

        path = Path(self._destination) / name
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / CCRUN_DIR_NAME).mkdir(exist_ok=True)
        except OSError as exc:
            raise CopyError(
                f"Не удалось создать папку бэкапа {path}: {exc}",
            ) from exc

        self._backup_dir = path
        logger.info("Создана папка бэкапа: %s", path)
        return path

    def backup(self, rel_path: str, dst_path: str) -> ManifestEntry:
        """Копирует dst_path в бэкап с проверкой. Возвращает entry.

        Бросает CopyError при любой ошибке. В этом случае в
        destination файл не тронут.
        """
        if self._backup_dir is None:
            self.ensure_dir()

        backup_path = self._backup_dir / rel_path

        try:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CopyError(
                f"Не удалось создать подкаталог бэкапа {rel_path}: {exc}",
            ) from exc

        tmp_path = str(backup_path) + TMP_SUFFIX

        # Убираем возможный мусор от прошлого запуска.
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError as exc:
            logger.debug("remove stale tmp %s: %r", tmp_path, exc)

        # 1. Копирование в .tmp
        try:
            shutil.copy2(dst_path, tmp_path)
        except OSError as exc:
            self._cleanup_tmp(tmp_path)
            raise CopyError(
                f"Не удалось скопировать бэкап для {rel_path}: {exc}",
            ) from exc

        # 2. Верификация
        try:
            self._verify(dst_path, tmp_path)
        except BackupVerificationError as exc:
            self._cleanup_tmp(tmp_path)
            raise CopyError(
                f"Бэкап {rel_path} не прошёл проверку: {exc}",
            ) from exc

        # 3. Атомарная фиксация
        try:
            os.replace(tmp_path, str(backup_path))
        except OSError as exc:
            self._cleanup_tmp(tmp_path)
            raise CopyError(
                f"Не удалось зафиксировать бэкап для {rel_path}: {exc}",
            ) from exc

        # Запись в манифест — только при успешном бэкапе.
        try:
            size = os.path.getsize(dst_path)
        except OSError as exc:
            logger.debug("размер %s: %r", dst_path, exc)
            size = 0

        entry = ManifestEntry(
            path=rel_path,
            size=size,
            mtime=iso_mtime(dst_path),
            action="replaced",
        )
        self._entries.append(entry)
        logger.debug("Бэкап заменяемого файла: %s", rel_path)
        return entry

    # --- Внутреннее ---

    @staticmethod
    def _verify(original: str, backup_tmp: str) -> None:
        try:
            orig_size = os.path.getsize(original)
            tmp_size = os.path.getsize(backup_tmp)
        except OSError as exc:
            raise BackupVerificationError(
                f"не удалось узнать размер: {exc}",
            ) from exc

        if orig_size != tmp_size:
            raise BackupVerificationError(
                f"размеры не совпадают ({orig_size} vs {tmp_size})",
            )

        try:
            same = filecmp.cmp(
                original, backup_tmp, shallow=False,
            )
        except Exception as exc:
            raise BackupVerificationError(
                f"сравнение не удалось: {exc}",
            ) from exc

        if not same:
            raise BackupVerificationError("содержимое отличается")

    @staticmethod
    def _cleanup_tmp(tmp_path: str) -> None:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError as exc:
            logger.debug("cleanup tmp %s: %r", tmp_path, exc)
