"""Общая hover-логика для плиток и пунктов списков.

Отслеживание «указатель всё ещё внутри» идёт не по событиям
<Enter>/<Leave> (они приходят при переходе на дочерний виджет),
а опросом winfo_containing через короткую задержку. Логика
одинакова для `nav_item` и `profile_tile`, поэтому вынесена сюда.

Наследник реализует `_apply_hover_bg(hover: bool)`.
"""

from __future__ import annotations

from ui.components.popup_utils import is_inside
from utils.logger import get_logger

logger = get_logger(__name__)

# Задержка перед проверкой позиции указателя после <Leave>.
_HOVER_CHECK_DELAY_MS = 20


class HoverMixin:
    """Подсветка при наведении с проверкой реальной позиции курсора."""

    _hover: bool = False

    def _apply_hover_bg(self, hover: bool) -> None:  # pragma: no cover
        raise NotImplementedError

    def _hover_on_enter(self, _event=None) -> None:
        if not self._hover:
            self._hover = True
            self._apply_hover_bg(True)

    def _hover_on_leave(self, _event=None) -> None:
        try:
            self.after(_HOVER_CHECK_DELAY_MS, self._hover_check)
        except Exception as exc:
            logger.debug("hover: after() не удался: %r", exc)
            self._hover = False
            self._apply_hover_bg(False)

    def _hover_check(self) -> None:
        try:
            under = self.winfo_containing(
                self.winfo_pointerx(), self.winfo_pointery(),
            )
        except Exception as exc:
            logger.debug("hover: winfo_containing: %r", exc)
            return
        if under is None or not is_inside(under, self):
            if self._hover:
                self._hover = False
                self._apply_hover_bg(False)
