import os
from pathlib import Path
import subprocess
import sys

import pytest
from qtpy.QtCore import QObject, QTimer, Signal
from qtpy.QtWidgets import QApplication, QMessageBox

from tests.test_main_window_navigation import _window


def control(panel, confirmed):
    class Control(QObject):
        closed = Signal()
        _stop_confirmed = confirmed
        def close(self): QTimer.singleShot(60, self.closed.emit)
    return Control(panel)


@pytest.mark.parametrize('confirmed', [True, False])
def test_main_window_hides_while_camera_closes(qtbot, tmp_path, monkeypatch, confirmed):
    warnings, quits = [], []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QApplication.instance(), 'quit', lambda: quits.append(True))
    window, controller = _window(qtbot, tmp_path)
    panel = window._exec_view._camera_panel
    panel._control = control(panel, confirmed)
    window.show()
    assert not window.close()
    assert not window.isVisible()
    assert panel._closing_control is not None
    assert not quits
    # Repeated close requests must neither repeat cleanup nor quit early.
    assert not window.close()
    qtbot.waitUntil(lambda: bool(quits))
    assert panel._closing_control is None
    assert panel._control_stop_failed is (not confirmed)
    assert controller.discards == 1
    assert not warnings


@pytest.mark.parametrize('mode', ['confirmed', 'unconfirmed', 'timeout'])
def test_background_sdk_cleanup_exits_real_application(tmp_path, mode):
    worker = tmp_path / 'sdk.py'
    worker.write_text('''import sys, time
print('IRON_CAMERA_CONTROL {"ready": true}', flush=True)
for line in sys.stdin:
    print('IRON_CAMERA_CONTROL {"method": "set_fov", "result": 0}', flush=True)
time.sleep(10 if sys.argv[1] == 'timeout' else .3)
if sys.argv[1] == 'confirmed':
    print('IRON_CAMERA_CONTROL {"stopped": true}', flush=True)
''')
    script = '''
import sys
from pathlib import Path
import qt_runtime
from qtpy.QtCore import QProcess, QTimer
from qtpy.QtWidgets import QApplication, QMessageBox
from camera.control_service import CameraControlService
from tests.test_main_window_navigation import _FakeController, _FakeLlmClient
from data.subject_store import SubjectStore
from ui.main_window import MainWindow
app = QApplication([])
window = MainWindow(subject_store=SubjectStore(Path(sys.argv[1])/'subjects.sqlite3'),
                    controller=_FakeController(), llm_client=_FakeLlmClient(),
                    enable_background_checks=False)
panel = window._exec_view._camera_panel
service = CameraControlService(panel, command=[sys.executable, '-u', sys.argv[2], sys.argv[3]])
panel._control = service
warnings, hidden_while_running, closed = [], [], []
QMessageBox.warning = lambda *args: warnings.append(args)
service._tracking_started = True
service._stop_confirmed = False
service.closed.connect(lambda: closed.append(service._process.state() == QProcess.NotRunning))
def start_close():
    window.close()
    QTimer.singleShot(50, check_hidden)
def check_hidden():
    hidden_while_running.append(not window.isVisible() and
                               service._process.state() == QProcess.Running)
service.idle.connect(start_close)
window.show()
service.request('set_fov', 0)
QTimer.singleShot(7000, app.quit)
app.exec()
assert hidden_while_running == [True], hidden_while_running
assert closed == [True], closed
assert not warnings, warnings
assert not window.isVisible()
assert panel._closing_control is None
assert panel._control_stop_failed == (sys.argv[3] != 'confirmed')
print('background cleanup passed')
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), str(worker), mode],
                            cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'background cleanup passed' in result.stdout
