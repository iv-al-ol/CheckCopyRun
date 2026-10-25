"""Примечание-подсказка под параметром.

Единый компонент для всех окон: одинаковый цвет, шрифт и,
главное, одинаковые отступы. Подсказка относится к параметру
над ней, поэтому сверху зазор маленький (`HINT_PADY_TOP`), а
снизу — нулевой: зазор до следующего параметра даёт его
собственный верхний отступ (`ITEM_PADY_TOP`).

Использование:

    HintLabel(parent, text="…").place_in_grid(row=row)

    HintLabel(parent, text="…").pack(
        fill="x", pady=HintLabel.pady(),
    )

`pady()` — единственный источник вертикальных отступов
примечаний: менять ритм нужно здесь, а не в каждом окне
отдельно. Горизонтальный отступ по умолчанию равен отступу
параметров настроек (`HINT_PADX`); если в окне параметры стоят
без отступа (форма профиля), передайте `padx=0`.
"""

from __future__ import annotations

from ui.components.wrapping_label import WrappingLabel
from ui.fonts import get_font
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "HINT_PADX",
    "HINT_PADY_TOP",
    "ITEM_PADY_TOP",
    "HintLabel",
]

# Единый вертикальный ритм для всех форм. Зазор всегда даёт
# ВЕРХНИЙ отступ элемента, а не нижний у предыдущего: иначе при
# стыковке «элемент без примечания → элемент с примечанием»
# оба отступа оказываются нулевыми и блоки склеиваются.
#
#   элемент → его примечание       = HINT_PADY_TOP  (маленький)
#   примечание → следующий элемент = ITEM_PADY_TOP  (обычный)
#   элемент → следующий элемент    = ITEM_PADY_TOP  (обычный)
HINT_PADY_TOP = 3

# Верхний отступ параметра. Работает и для первого параметра
# после заголовка секции — он не прилипает к блоку над ним.
ITEM_PADY_TOP = 10

_FONT_SIZE = 11

# Запас при расчёте переноса строк (wraplength = ширина - запас).
# Не влияет на положение текста по горизонтали — оно задаётся
# `padx` при размещении, как и у параметра над примечанием.
_HPADDING = 4
_TEXT_COLOR = ("gray40", "gray60")

# Горизонтальный отступ примечания. Совпадает с отступом
# параметров (`padx=4`), поэтому текст начинается под чекбоксом.
HINT_PADX = 4


class HintLabel(WrappingLabel):
    """Текст примечания с единым оформлением и отступами."""

    def __init__(self, master, *, h_padding: int = _HPADDING, **kwargs):
        kwargs.setdefault("text_color", _TEXT_COLOR)
        kwargs.setdefault("font", get_font(_FONT_SIZE))
        # Текст прижат к верхнему краю: иначе у одно-строчного
        # примечания он «всплывает» к середине блока, и видимый
        # зазор до параметра оказывается больше, чем у
        # много-строчного. Отступы должны быть одинаковыми.
        kwargs.setdefault("anchor", "nw")
        super().__init__(master, h_padding=h_padding, **kwargs)
        self._applied_height = -1

    def _apply_wraplength(self) -> None:
        """Пересчитывает перенос и подгоняет высоту под текст."""
        super()._apply_wraplength()
        self._fit_height()

    def _fit_height(self) -> None:
        """Сжимает блок до высоты текста.

        `CTkLabel` держит фиксированную высоту (28 px) и
        центрирует текст в ней. У одно-строчного примечания это
        даёт лишние 9 px сверху, у много-строчного — нет, из-за
        чего визуальные зазоры расходятся. Высота блока должна
        совпадать с высотой текста: тогда `pady` — это и есть
        реальный зазор.
        """
        label = getattr(self, "_label", None)
        if label is None:
            return
        try:
            need = label.winfo_reqheight()
            if need <= 1:
                return
            if self._applied_height == need:
                return
            self._applied_height = need
            self.configure(height=need)
        except Exception as exc:
            logger.debug("HintLabel._fit_height: %r", exc)

    @staticmethod
    def pady() -> tuple[int, int]:
        """Отступы примечания: (сверху, снизу).

        Сверху маленький — примечание относится к параметру над
        ним. Снизу нулевой — зазор до следующего блока даёт сам
        следующий блок.
        """
        return HINT_PADY_TOP, 0

    @staticmethod
    def item_pady() -> tuple[int, int]:
        """Отступы параметра, у которого есть примечание.

        Верхний отступ обычный — отбивает параметр от блока над
        ним. Нижний нулевой: между параметром и его примечанием
        зазор задаёт `HINT_PADY_TOP` примечания.
        """
        return ITEM_PADY_TOP, 0

    @staticmethod
    def item_pady_plain() -> tuple[int, int]:
        """Отступы параметра, у которого примечания нет."""
        return ITEM_PADY_TOP, 0

    def place_in_grid(
        self,
        *,
        row: int,
        column: int = 0,
        columnspan: int = 1,
        sticky: str = "ew",
        padx: int = HINT_PADX,
    ) -> None:
        """Размещает примечание в grid с едиными отступами.

        Вертикальные отступы всегда берутся из компонента.
        `padx` по умолчанию совпадает с отступом параметров
        настроек; в форме профиля параметры стоят без отступа,
        поэтому там передаётся `padx=0`.

        `columnspan` нужен там, где параметр занимает несколько
        колонок (подпись + поле + единица): примечание должно
        растягиваться на всю их ширину.
        """
        self.grid(
            row=row, column=column, columnspan=columnspan,
            sticky=sticky, padx=padx, pady=self.pady(),
        )

    def set_enabled(self, enabled: bool) -> None:
        """Гасит текст, когда параметр заблокирован.

        Нужно, чтобы примечание визуально выключалось вместе с
        чекбоксом, к которому относится.
        """
        color = _TEXT_COLOR if enabled else ("gray55", "gray45")
        try:
            self.configure(text_color=color)
        except Exception as exc:
            logger.debug("HintLabel.set_enabled: %r", exc)
