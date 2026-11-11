"""Entry point for the Chronos application."""
import logging
import sys

import win32api
import win32event
import winerror
from PyQt5 import QtWidgets

from . import storage
from .paths import get_log_path
from .ui.main_window import MainWindow

MUTEX_NAME = "Global\\Chronos_SingleInstance"


def _setup_logging() -> None:
    logging.basicConfig(
        filename=get_log_path(),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    _setup_logging()
    logger = logging.getLogger(__name__)

    # Single-instance guard: autostart (logon), manual launch, and the
    # post-reboot resume can all try to start the app at the same time.
    win32event.CreateMutex(None, False, MUTEX_NAME)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        logger.info("Another instance is already running, exiting")
        return

    storage.init_db()

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.resume_power_cycle_if_pending()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
