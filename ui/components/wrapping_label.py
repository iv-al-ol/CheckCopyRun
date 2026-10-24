"""CTkLabel с автоматическим переносом строк по ширине родителя.

При создании мы напрямую задаём начальный wraplength внутреннему
tkinter.Label. Без этого Label запрашивает ширину по всей длине
текста, раздувает родителя (до 1000+ px), и текст выходит за
пределы окна. CTkLabel не поддерживает wraplength на уровне
фрейма, поэтому мы обращаемся напрямую к внутреннему _label.

При <Configure> (изменение выделенной ширины) wraplength
пересчитывается по self.winfo_width() — это фактическая
ширина, выделенная grid/pack, с учётом sticky="ew".
"""

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger(__name__)

_REFLOW_DELAY_MS = 30
_MIN_WRAPLENGTH = 120
_DEFAULT_WRAPLENGTH = 200


class WrappingLabel(ctk.CTkLabel):
    """Текст переносится по словам, ширина подстраивается под родителя."""

    def __init__(
        self,
        master,
        *,
        h_padding: int = 32,
        **kwargs,
    ):
        # Удаляем wraplength из kwargs, чтобы он не попал в tkinter.Frame
        # (CTkLabel не поддерживает его в конструкторе фрейма).
        kwargs.pop("wraplength", None)
        kwargs.setdefault("anchor", "w")
        kwargs.setdefault("justify", "left")
        super().__init__(master, **kwargs)

        self._h_padding = h_padding
        self._reflow_job: str | None = None

        # Задаём начальный wraplength напрямую в внутренний Label,
        # чтобы он не запрашивал гигантскую ширину при первом рендере.
        if hasattr(self, "_label"):
            self._label.configure(wraplength=_DEFAULT_WRAPLENGTH)

        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event=None) -> None:
        if self._reflow_job is not None:
            try:
                self.after_cancel(self._reflow_job)
            except Exception as exc:
                logger.debug(
                    "after_cancel для wraplength не удался: %r", exc,
                )
        self._reflow_job = self.after(
            _REFLOW_DELAY_MS, self._apply_wraplength,
        )

    def _apply_wraplength(self) -> None:
        self._reflow_job = None

        width = self.winfo_width()
        if width <= 1:
            try:
                width = self.master.winfo_width()
            except Exception:
                return

        if width <= 1:
            return

        wraplength = max(
            _MIN_WRAPLENGTH, width - self._h_padding,
        )

        # Проверка, чтобы не вызывать configure() без нужды
        try:
            current = int(self._label.cget("wraplength"))
            if current == wraplength:
                return
        except (ValueError, TypeError, AttributeError):
            pass

        try:
            self._label.configure(wraplength=wraplength)
        except Exception as exc:
            logger.debug("configure(wraplength) не удался: %r", exc)
