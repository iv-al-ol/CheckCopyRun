"""Модель множественного выделения элементов списка.

Не зависит от tkinter — тестируется отдельно.

Семантика совпадает с Проводником Windows:
  • обычный клик — выделить только этот;
  • Ctrl+клик  — toggle (добавить/убрать);
  • Shift+клик — выделить диапазон от anchor до текущего;
  • ПКМ по невыделенному — выделить только его;
  • рамка (drag) — заменить выделение тем, что попало.

«Anchor» — последний кликнутый без Shift элемент; от него
строится диапазон для Shift.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SelectionModel:
    _order: list[str] = field(default_factory=list)
    _selected: set[str] = field(default_factory=set)
    _anchor: str | None = None

    # --- Состав ---

    def set_items(self, ids: list[str]) -> None:
        """Обновить список известных id (при rebuild).

        Выделение пересчитывается: остаются только существующие
        id. Anchor сбрасывается, если его больше нет в списке.
        """
        self._order = list(ids)
        known = set(ids)
        self._selected &= known
        if self._anchor is not None and self._anchor not in known:
            self._anchor = None

    def clear(self) -> None:
        self._selected.clear()
        self._anchor = None

    def is_selected(self, pid: str) -> bool:
        return pid in self._selected

    def get_selected(self) -> list[str]:
        """В порядке отображения — предсказуемо для UI."""
        return [pid for pid in self._order if pid in self._selected]

    def get_selected_set(self) -> set[str]:
        return set(self._selected)

    def count(self) -> int:
        return len(self._selected)

    # --- Действия ---

    def select_only(self, pid: str) -> None:
        self._selected = {pid}
        self._anchor = pid

    def toggle(self, pid: str) -> None:
        if pid in self._selected:
            self._selected.discard(pid)
            if self._anchor == pid:
                self._anchor = None
        else:
            self._selected.add(pid)
            self._anchor = pid

    def select_range(self, pid: str) -> None:
        if self._anchor is None:
            self.select_only(pid)
            return
        try:
            a = self._order.index(self._anchor)
            b = self._order.index(pid)
        except ValueError:
            self.select_only(pid)
            return
        lo, hi = (a, b) if a <= b else (b, a)
        self._selected = set(self._order[lo:hi + 1])
        # Anchor не меняем — следующая Shift-операция снова
        # должна расширяться/сужаться от исходной точки.

    def select_many(self, ids: list[str]) -> None:
        """Заменить выделение заданным набором (рамка)."""
        known = set(self._order)
        self._selected = {i for i in ids if i in known}
        self._anchor = ids[-1] if ids else None

    # --- Обработчики событий ---

    def handle_click(
        self, pid: str, *, ctrl: bool, shift: bool,
    ) -> None:
        if shift:
            self.select_range(pid)
            self._anchor = pid
        elif ctrl:
            self.toggle(pid)
            self._anchor = pid
        else:
            self.select_only(pid)

    def handle_right_click(self, pid: str) -> None:
        """ПКМ: если pid не в выделении — выделить его одного."""
        if pid not in self._selected:
            self.select_only(pid)

    # --- Рамка ---

    def ids_in_rect(
        self,
        rect: tuple[int, int, int, int],
        item_rects: dict[str, tuple[int, int, int, int]],
    ) -> list[str]:
        """Все id, чьи прямоугольники пересекаются с rect.

        rect: (x1, y1, x2, y2) — экранные координаты.
        item_rects: {id: (x1, y1, x2, y2)}.
        Возврат — в порядке _order.
        """
        x1, y1, x2, y2 = rect
        hit: set[str] = set()
        for pid, (ix1, iy1, ix2, iy2) in item_rects.items():
            if ix1 < x2 and ix2 > x1 and iy1 < y2 and iy2 > y1:
                hit.add(pid)
        return [pid for pid in self._order if pid in hit]
