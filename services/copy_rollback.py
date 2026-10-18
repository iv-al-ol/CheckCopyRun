"""Откат destination к состоянию «до копирования» при отмене.

Порядок:
  1. Восстановить заменённые файлы из бэкапа.
  2. Учесть замены, которые прошли без бэкапа — они невосстановимы.
  3. Удалить созданные нами файлы.
  4. Удалить созданные нами пустые директории.

RollbackResult.succeeded = True только если errors == 0.
Замены без бэкапа всегда дают errors: их восстановить нельзя.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from services.copy_constants import TMP_SUFFIX
from services.copy_manifest import ManifestEntry
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RollbackResult:
    attempted: bool = True
    restored: int = 0
    deleted: int = 0
    errors: int = 0

    @property
    def succeeded(self) -> bool:
        return self.errors == 0


class RollbackManager:
    """Возвращает destination к состоянию «до копирования»."""

    def __init__(
        self,
        destination: str,
        backup_dir: Path | None,
    ):
        self._destination = destination
        self._backup_dir = backup_dir

    def rollback(
        self,
        *,
        replaced_entries: list[ManifestEntry],
        replaced_without_backup: list[str],
        created_files: list[str],
        created_dirs: set[str],
    ) -> RollbackResult:
        result = RollbackResult()
        logger.info(
            "Отмена: откат изменений в %s "
            "(заменено с бэкапом %d, без бэкапа %d, создано %d)",
            self._destination,
            len(replaced_entries),
            len(replaced_without_backup),
            len(created_files),
        )

        # 1. Восстановить замены с бэкапом.
        if replaced_entries:
            if self._backup_dir is None:
                logger.error(
                    "Замены есть, но бэкап-папка отсутствует",
                )
                result.errors += len(replaced_entries)
            else:
                for entry in replaced_entries:
                    if self._restore_one(entry):
                        result.restored += 1
                    else:
                        result.errors += 1

        # 2. Замены без бэкапа — восстановить невозможно.
        if replaced_without_backup:
            logger.warning(
                "Замены без бэкапа не могут быть восстановлены: %d",
                len(replaced_without_backup),
            )
            result.errors += len(replaced_without_backup)

        # 3. Удалить созданные файлы.
        for rel_path in created_files:
            if self._delete_created(rel_path):
                result.deleted += 1
            else:
                result.errors += 1

        # 4. Удалить созданные пустые директории (не критично).
        self._cleanup_empty_dirs(created_dirs)

        if result.succeeded:
            logger.info(
                "Откат завершён: восстановлено %d, удалено %d",
                result.restored, result.deleted,
            )
        else:
            logger.warning(
                "Откат частичный: восстановлено %d, удалено %d, "
                "ошибок %d",
                result.restored, result.deleted, result.errors,
            )

        return result

    # --- Внутреннее ---

    def _restore_one(self, entry: ManifestEntry) -> bool:
        if self._backup_dir is None:
            return False

        backup_path = self._backup_dir / entry.path
        dst_path = Path(self._destination) / entry.path

        try:
            if not backup_path.is_file():
                logger.error(
                    "Откат: бэкап %s отсутствует", entry.path,
                )
                return False

            # Через .tmp + os.replace — на случай, если файл в
            # destination в промежуточном состоянии.
            try:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.error(
                    "Откат: не создать %s: %r",
                    dst_path.parent, exc,
                )
                return False

            tmp_path = str(dst_path) + TMP_SUFFIX
            shutil.copy2(str(backup_path), tmp_path)
            os.replace(tmp_path, str(dst_path))
            logger.debug("Откат: восстановлен %s", entry.path)
            return True
        except Exception as exc:
            logger.error(
                "Откат не удался для %s: %r", entry.path, exc,
            )
            return False

    def _delete_created(self, rel_path: str) -> bool:
        dst_path = Path(self._destination) / rel_path
        try:
            if dst_path.is_file():
                dst_path.unlink()
                logger.debug("Откат: удалён созданный %s", rel_path)
            return True
        except Exception as exc:
            logger.error(
                "Не удалось удалить созданный %s: %r",
                rel_path, exc,
            )
            return False

    @staticmethod
    def _cleanup_empty_dirs(created_dirs: set[str]) -> None:
        # Удаляем снизу вверх: сначала самые глубокие директории.
        dirs = sorted(
            created_dirs,
            key=lambda p: p.count(os.sep),
            reverse=True,
        )
        for d in dirs:
            try:
                os.rmdir(d)   # удаляет только если пустая
                logger.debug(
                    "Откат: удалена пустая директория %s", d,
                )
            except OSError as exc:
                logger.debug("rmdir %s: %r", d, exc)
