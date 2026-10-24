"""Очистка неиспользуемых иконок приложений.

В icons/ (Documents/CheckCopyRun/icons) хранятся PNG, извлечённые
из exe. Имена: exe_<SHA-1 от пути>.png.

При удалении профиля или смене иконки старые PNG становятся
мусором. Функция cleanup_unused_icons проходит по всем профилям,
собирает используемые пути и удаляет всё остальное, что совпадает
с шаблоном exe_*.png.

Не трогает пользовательские картинки, лежащие вне icons/ — там
хранится только путь в profile.icon.
"""

from __future__ import annotations

from pathlib import Path

from core.models import AppSettings
from core.settings_store import get_icons_dir
from ui.components.image_utils import looks_like_image_path
from utils.logger import get_logger

logger = get_logger(__name__)

_EXE_ICON_PREFIX = "exe_"
_EXE_ICON_SUFFIX = ".png"


def cleanup_unused_icons(
    settings: AppSettings,
    icons_dir: Path | None = None,
) -> int:
    """Удаляет неиспользуемые PNG, извлечённые из exe.

    Возвращает количество удалённых файлов.

    icons_dir — для тестов. По умолчанию — get_icons_dir().
    """
    if icons_dir is None:
        icons_dir = get_icons_dir()

    if not icons_dir.exists():
        return 0

    # Собираем все пути, на которые ссылается хотя бы один профиль.
    used: set[str] = set()
    for profile in settings.profiles:
        icon = profile.icon
        if not icon or not looks_like_image_path(icon):
            continue
        try:
            used.add(str(Path(icon).resolve()))
        except OSError as exc:
            logger.debug("resolve %r: %r", icon, exc)

    pattern = f"{_EXE_ICON_PREFIX}*{_EXE_ICON_SUFFIX}"
    deleted = 0

    for png in icons_dir.glob(pattern):
        try:
            resolved = str(png.resolve())
        except OSError as exc:
            logger.debug("resolve %r: %r", png, exc)
            continue

        if resolved in used:
            continue

        try:
            png.unlink()
            deleted += 1
            logger.debug("Удалена неиспользуемая иконка: %s", png)
        except OSError as exc:
            logger.debug("Не удалось удалить %s: %r", png, exc)

    if deleted > 0:
        logger.info(
            "Очистка иконок: удалено %d файлов из %s",
            deleted, icons_dir,
        )

    return deleted
