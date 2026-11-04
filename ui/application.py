"""Native Qt application lifecycle for desktop entry points."""

from contextlib import contextmanager
import sys

from qtpy.QtWidgets import QApplication
from ui.styles import CONTROL_QSS


@contextmanager
def application():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(CONTROL_QSS)
    yield app
    app.exec()
