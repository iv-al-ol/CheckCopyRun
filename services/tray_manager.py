"""Обёртка над TrayIcon: управление жизненным циклом трея."""

from collections.abc import Callable
from pathlib import Path

from services.tray import TrayIcon
from utils.logger import get_logger

logger = get_logger(__name__)


class TrayManager:
    """Запускает и останавливает иконку в трее по запросу окна."""

    def __init__(
        self,
        icon_path: Path | None,
        title: str,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self._icon_path = icon_path
        self._title = title
        self._on_show = on_show
        self._on_quit = on_quit
        self._tray: TrayIcon | None = None

    @property
    def is_active(self) -> bool:
        return self._tray is not None

    def start(self) -> bool:
        if self._tray is not None:
            return True
        if self._icon_path is None:
            return False

        tray = TrayIcon(
            icon_path=self._icon_path,
            title=self._title,
            on_show=self._on_show,
            on_quit=self._on_quit,
        )
        if tray.is_supported and tray.start():
            self._tray = tray
            return True
        return False

    def stop(self) -> None:
        if self._tray is None:
            return
        try:
            self._tray.stop()
        except Exception as exc:
            logger.error(f"ошибка остановки трея: {exc!r}")
        self._tray = None
