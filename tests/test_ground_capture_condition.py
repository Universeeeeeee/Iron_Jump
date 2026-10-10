"""Diagnostic hooks preserve byte delivery and native call cardinality."""
import ctypes
from types import SimpleNamespace
import pytest
from tools.ground_capture_condition import observe, capture_parameters
from hardware.sensor_frame import DeviceLayout, SensorFrame


class Recorder:
    def __init__(self):
        self.events, self.raw = [], []
    def log_status(self, event, **kwargs):
        self.events.append((event, kwargs))
    def record_raw(self, data):
        self.raw.append(data)


@pytest.mark.parametrize('fails', [False, True])
def test_observer_calls_original_once_restores_and_retains_failure(tmp_path, monkeypatch, fails):
    loaded = tmp_path / 'loaded.dll'; loaded.write_bytes(b'dll-source')
    class Lookup:
        def __call__(self, handle, buffer, length):
            assert handle == 123
            buffer.value = str(loaded)
            return len(buffer.value)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **k: SimpleNamespace(GetModuleFileNameW=Lookup()), raising=False)
    class DLL:
        def __init__(self):
            self._lib = SimpleNamespace(_handle=123)
            self.calls = []
        def native(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            if fails:
                raise RuntimeError('native-failure')
            return True
        start_capture = stop_capture = send_command_frame = write = set_timeout = native
    class Device:
        start_auto_read = stop_auto_read = lambda self, *a, **k: 0
    class Worker:
        def __init__(self):
            self.timeout_ms, self.chunk_size = 10, 2048
            self.vid, self.pid = 0x04B4, 0x1004
            self.capture_command_required, self.legacy_frame_signals, self.dll_path = True, False, str(loaded)
            self.device_state_changed = self.acquisition_issue = SimpleNamespace(connect=lambda cb: None)
            self.received = []
        def _on_bytes(self, data):
            self.received.append(data)
        def _discard_startup_input(self):
            return 7
        def _publish_frame(self, frame):
            return frame
        def stop(self):
            return 8
    originals = (Worker.__init__, Worker._on_bytes, DLL.__init__, DLL.write, Device.start_auto_read)
    recorder = Recorder(); restore = observe(Worker, Device, DLL, recorder)
    try:
        worker, dll = Worker(), DLL()
        payload = b'\x00\xff\x5a'; worker._on_bytes(payload)
        assert worker._discard_startup_input() == 7
        frame = SensorFrame('test', DeviceLayout.linear(1), 10, 0, 1000, bytes(96), b'\x01'*96, bytes(12))
        assert worker._publish_frame(frame) is frame
        assert worker._publish_frame(frame) is frame
        assert sum(k == 'frame_quality_snapshot' for k, v in recorder.events) == 1
        assert worker.stop() == 8
        assert next(v for k, v in recorder.events if k == 'worker_stopped')['last_frame_index'] == 10
        if fails:
            with pytest.raises(RuntimeError, match='native-failure'):
                dll.write(payload)
        else:
            assert dll.write(payload) is True
        assert len(dll.calls) == 1 and worker.received == recorder.raw == [payload]
        assert next(v for k, v in recorder.events if k == 'loaded_dll')['os_module_path'] == str(loaded)
        assert any(k == ('sdk_exception' if fails else 'sdk_result') for k, v in recorder.events)
    finally:
        restore()
    assert originals == (Worker.__init__, Worker._on_bytes, DLL.__init__, DLL.write, Device.start_auto_read)


def test_minimal_parameters_follow_main_environment_defaults_and_hex(monkeypatch):
    monkeypatch.setenv('DAYU_VID', '0x1234'); monkeypatch.setenv('DAYU_PID', '4661')
    monkeypatch.setenv('DAYU_TIMEOUT', '25'); monkeypatch.setenv('DAYU_CHUNK', 'invalid')
    assert capture_parameters() == {'vid': 0x1234, 'pid': 4661, 'timeout_ms': 25, 'chunk_size': 2048}
