"""Release Qt deferred widgets and Python reference cycles between tests."""
import gc
import pytest
from qtpy.QtCore import QCoreApplication, QEvent


@pytest.fixture(autouse=True)
def release_qt_test_objects():
    yield
    # pytest-qt closes widgets with deleteLater; processEvents alone does not
    # deliver DeferredDelete without an outer application event loop.
    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()
