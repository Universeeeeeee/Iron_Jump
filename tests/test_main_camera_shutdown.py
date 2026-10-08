from qtpy.QtCore import QObject, QTimer, Signal
from qtpy.QtWidgets import QMessageBox

from tests.test_main_window_navigation import _window


def control(panel, confirmed):
    class Control(QObject):
        closed = Signal()
        _stop_confirmed = confirmed
        def close(self): QTimer.singleShot(60, self.closed.emit)
    return Control(panel)


def test_main_window_keeps_event_loop_until_camera_owner_closes(qtbot, tmp_path):
    window, controller = _window(qtbot, tmp_path)
    panel = window._exec_view._camera_panel
    panel._control = control(panel, True)
    window.show()
    assert not window.close()
    assert window.isVisible()
    assert panel._closing_control is not None
    qtbot.waitUntil(lambda: not window.isVisible())
    assert panel._closing_control is None
    assert controller.discards == 1


def test_main_window_reports_unconfirmed_stop_and_waits_for_operator(qtbot, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    window, controller = _window(qtbot, tmp_path)
    panel = window._exec_view._camera_panel
    panel._control = control(panel, False)
    window.show()
    assert not window.close()
    qtbot.waitUntil(lambda: bool(warnings))
    assert window.isVisible()
    assert panel._control_stop_failed
    assert window.close()
    assert controller.discards == 1
