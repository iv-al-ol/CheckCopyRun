"""CTkLabel с автоматическим переносом строк по ширине родителя."""

import customtkinter as ctk

from utils.logger import get_logger

logger = get_logger(__name__)

_REFLOW_DELAY_MS = 30
_MIN_WRAPLENGTH = 120


class WrappingLabel(ctk.CTkLabel):
    """Текст переносится по словам, ширина подстраивается под родителя."""

    def __init__(
        self,
        master,
        *,
        h_padding: int = 32,
        **kwargs,
    ):
        kwargs.setdefault("anchor", "w")
        kwargs.setdefault("justify", "left")
        super().__init__(master, **kwargs)

        self._h_padding = h_padding
        self._reflow_job: str | None = None

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

        try:
            parent_width = self.master.winfo_width()
        except Exception as exc:
            logger.debug(
                "не удалось получить ширину родителя: %r", exc,
            )
            return

        if parent_width <= 1:
            return

        wraplength = max(
            _MIN_WRAPLENGTH, parent_width - self._h_padding,
        )

        try:
            self.configure(wraplength=wraplength)
        except Exception as exc:
            logger.debug("configure(wraplength) не удался: %r", exc)
