"""Slow SDK responses must not freeze Qt or accumulate stale settings."""
import sys
import time

from qtpy.QtCore import QProcess, QTimer

from camera.control_service import CameraControlService


def fake_worker(tmp_path):
    script = tmp_path/'control.py'
    script.write_text('''import json, sys, time
time.sleep(.4)
print('native SDK log', flush=True)
print('IRON_CAMERA_CONTROL '+json.dumps({'ready':True}), flush=True)
for line in sys.stdin:
    r=json.loads(line)
    time.sleep(.03)
    print('IRON_CAMERA_CONTROL '+json.dumps({'method':r['method'],'result':r['args'][0] if r['args'] else 0}), flush=True)
''')
    return [sys.executable, '-u', str(script)]


def test_slow_init_keeps_ui_responsive_and_coalesces_settings(qtbot, tmp_path):
    service = CameraControlService(command=fake_worker(tmp_path))
    replies, beats, idle_replies = [], [], []
    service.completed.connect(lambda *r: replies.append(r))
    service.idle.connect(lambda: idle_replies.append(list(replies)))
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: beats.append(time.perf_counter()))
    timer.start()
    try:
        start = time.perf_counter()
        for i in range(200):
            service.request('set_fov', i)
        service.request('set_ai_mode', 4)
        service.request('set_ai_off')
        assert time.perf_counter()-start < .15
        qtbot.waitUntil(lambda: len(replies)==2, timeout=5000)
        assert len(beats) >= 10
        assert replies == [('set_fov',199), ('set_ai_off',0)]
        assert idle_replies == [replies]
        # SDK ownership persists after a response; no one-shot process teardown.
        assert service._process.state() == QProcess.Running
        service.request('set_ai_mode',4)
        qtbot.waitUntil(lambda: len(replies)==3)
        assert replies[-1] == ('set_ai_mode',4)
        assert len(idle_replies) == 2
    finally:
        timer.stop()
        service.close()
    qtbot.waitUntil(lambda: service._process.state() == QProcess.NotRunning, timeout=4000)


def test_close_during_initialization_discards_queued_control(qtbot, tmp_path):
    service = CameraControlService(command=fake_worker(tmp_path))
    replies = []
    service.completed.connect(lambda *r: replies.append(r))
    service.request('set_ai_mode',4)
    service.close()
    qtbot.wait(450)
    assert not replies
    qtbot.waitUntil(lambda: service._process.state() == QProcess.NotRunning, timeout=4000)


def test_auto_tracking_once_and_explicit_off_is_respected(qtbot):
    from ui.embedded_camera_panel import EmbeddedCameraPanel
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    calls = []
    class Control:
        def request(self, *args): calls.append(args)
        def close(self): pass
        def deleteLater(self): pass
    class Vision:
        def display_state(self): return object(), '人体已识别', None
        def stop(self): pass
    panel._control = Control()
    panel._vision = Vision()
    panel._preview_active = True
    panel._show_latest_frame()
    panel._show_latest_frame()
    assert calls == [('set_ai_mode',4)]
    panel._on_ai_off()
    panel._show_latest_frame()
    assert calls == [('set_ai_mode',4), ('set_ai_off',)]
    panel.shutdown()


def test_capture_waits_for_settings_and_cancel_prevents_late_start(qtbot, monkeypatch):
    from qtpy.QtCore import QObject, Signal
    import camera.control_service as module
    from ui.embedded_camera_panel import EmbeddedCameraPanel

    class Control(QObject):
        completed = Signal(str, int)
        failed = Signal(str)
        idle = Signal()
        def __init__(self, parent=None):
            super().__init__(parent)
            self.calls = []
        def request(self, *args): self.calls.append(args)
        def close(self): pass
    class Capture(QObject):
        frame_ready = Signal(object)
        recording_finished = Signal(str)
        error = Signal(str)
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(module, 'CameraControlService', Control)
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    created = []
    def create():
        capture = Capture()
        created.append(capture)
        return capture
    monkeypatch.setattr(panel, '_create_capture', create)
    try:
        panel.start_preview()
        control = panel._control
        assert len(control.calls) == 5
        assert not created
        # Repeated clicks while initializing must not enqueue another startup.
        panel.start_preview()
        assert len(control.calls) == 5
        control.completed.emit('set_fov', 0)
        assert not created
        control.idle.emit()
        assert len(created) == 1
        control.idle.emit()
        assert len(created) == 1
        panel.shutdown()
        panel.start_preview()
        pending = panel._control
        panel.stop_preview()
        pending.idle.emit()
        assert len(created) == 1
    finally:
        panel.shutdown()


def test_control_init_failure_does_not_start_capture(qtbot, monkeypatch):
    from qtpy.QtCore import QObject, Signal
    import camera.control_service as module
    from ui.embedded_camera_panel import EmbeddedCameraPanel
    class Control(QObject):
        completed = Signal(str, int)
        failed = Signal(str)
        idle = Signal()
        def request(self, *args): pass
        def close(self): pass
    monkeypatch.setattr(module, 'CameraControlService', Control)
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    started = []
    monkeypatch.setattr(panel, '_start_capture', lambda: started.append(True), raising=False)
    try:
        panel.start_preview()
        failed_control = panel._control
        failed_control.failed.emit('连接失败')
        failed_control.idle.emit()
        assert not started
        assert '连接失败' in panel._preview.text()
        panel.start_preview()
        assert panel._control is not failed_control
        failed_control.idle.emit()
        assert not started
        panel._control.idle.emit()
        assert started == [True]
    finally:
        panel.shutdown()
