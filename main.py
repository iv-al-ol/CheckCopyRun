"""Точка входа CheckCopyRun."""

from __future__ import annotations

import sys

from ui.app import MainWindow
from utils.logger import setup_logging


def main() -> int:
    setup_logging()
    app = MainWindow()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
