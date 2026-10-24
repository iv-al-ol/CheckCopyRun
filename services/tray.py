"""Иконка приложения в системном трее."""

import threading
from collections.abc import Callable
from pathlib import Path

try:
    import pystray
    from PIL import Image
except ImportError:
    pystray = None
    Image = None

from config.constants import APP_NAME
from utils.logger import get_logger

logger = get_logger(__name__)


class TrayIcon:
    """
    Иконка в трее с двумя действиями: показать окно и выйти.

    on_show / on_quit вызываются из потока pystray. Вызывающий код
    должен сам решить, как безопасно передать управление в Tk-поток
    (обычно через App.after(0, ...)).
    """

    def __init__(
        self,
        icon_path: Path,
        title: str,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self._icon_path = Path(icon_path)
        self._title = title
        self._on_show = on_show
        self._on_quit = on_quit

        self._icon = None
        self._thread: threading.Thread | None = None

    @property
    def is_supported(self) -> bool:
        return pystray is not None and Image is not None

    def start(self) -> bool:
        if not self.is_supported:
            logger.error(
                "pystray или PIL не установлены — трей недоступен"
            )
            return False

        if self._icon is not None:
            return True

        if not self._icon_path.exists():
            logger.error(f"файл иконки не найден: {self._icon_path!r}")
            return False

        try:
            image = Image.open(self._icon_path)
        except Exception as exc:
            logger.error(
                f"не удалось открыть иконку {self._icon_path!r}: {exc!r}"
            )
            return False

        menu = pystray.Menu(
            pystray.MenuItem(
                "Показать", self._handle_show, default=True
            ),
            pystray.MenuItem("Выход", self._handle_quit),
        )

        try:
            self._icon = pystray.Icon(
                APP_NAME, image, self._title, menu
            )
            self._thread = threading.Thread(
                target=self._icon.run, daemon=True
            )
            self._thread.start()
        except Exception as exc:
            logger.error(f"не удалось запустить трей: {exc!r}")
            self._icon = None
            return False

        logger.debug(f"трей запущен, иконка: {self._icon_path!r}")
        return True

    def stop(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception as exc:
            logger.error(f"ошибка остановки трея: {exc!r}")
        self._icon = None
        self._thread = None

    def notify(self, message: str, title: str | None = None) -> None:
        """Balloon-уведомление из иконки."""
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title or self._title)
        except Exception as exc:
            logger.error(f"ошибка уведомления из трея: {exc!r}")

    # --- Обработчики ---

    def _handle_show(self, *args) -> None:
        try:
            self._on_show()
        except Exception as exc:
            logger.error(f"ошибка в обработчике «Показать»: {exc!r}")

    def _handle_quit(self, *args) -> None:
        try:
            self._on_quit()
        except Exception as exc:
            logger.error(f"ошибка в обработчике «Выход»: {exc!r}")
