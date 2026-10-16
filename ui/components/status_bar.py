"""Статус-бар с прогрессом."""


import customtkinter as ctk


class StatusBar(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, height=30, corner_radius=0)
        self.grid_propagate(False)

        self.label = ctk.CTkLabel(
            self, text="Готово", anchor="w",
            font=ctk.CTkFont(size=12),
        )
        self.label.pack(side="left", padx=12, fill="x", expand=True)

        self.percent_label = ctk.CTkLabel(
            self, text="", anchor="e",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.progress = ctk.CTkProgressBar(self, width=220, height=12)
        self.progress.set(0.0)
        self._progress_visible = False

    def set_text(self, text: str) -> None:
        self.label.configure(text=text)

    def show_progress(self, value: float | None) -> None:
        if value is None:
            if self._progress_visible:
                self.progress.pack_forget()
                self.percent_label.pack_forget()
                self._progress_visible = False
            return

        if not self._progress_visible:
            self.percent_label.pack(side="right", padx=(0, 8))
            self.progress.pack(side="right", padx=(0, 12))
            self._progress_visible = True

        v = max(0.0, min(1.0, float(value)))
        self.progress.set(v)
        self.percent_label.configure(text=f"{int(round(v * 100))}%")
