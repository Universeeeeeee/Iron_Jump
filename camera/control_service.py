"""Persistent SDK process: camera settings must not block the Qt UI thread."""
import json
import queue
import sys
import threading
from pathlib import Path

from qtpy.QtCore import QObject, QProcess, QTimer, Signal

PREFIX = 'IRON_CAMERA_CONTROL '
METHODS = {'set_fov', 'set_auto_focus', 'set_exposure_compensation',
           'set_anti_flicker', 'set_wdr', 'set_ai_mode', 'set_ai_off',
           'tracking_start', 'tracking_stop'}


class CameraControlService(QObject):
    completed = Signal(str, int)
    failed = Signal(str)
    idle = Signal()
    closed = Signal()
    tracking_event = Signal(object)

    def __init__(self, parent=None, *, command=None):
        super().__init__(parent)
        self._command = command or [sys.executable, '-u', '-m', 'camera.control_service']
        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._read)
        self._process.errorOccurred.connect(self._error)
        self._process.finished.connect(self._finished)
        self._ready = self._busy = self._closing = False
        self._pending = {}
        self._output = bytearray()
        self._generation = 0
        self._relay = None
        self._tracking = False
        self._tracking_started = False
        self._stop_confirmed = True
        self._pose_timer = QTimer(self)
        self._pose_timer.setInterval(50)
        self._pose_timer.timeout.connect(self._send_pose)

    def begin_tracking(self):
        from camera.pose_transport import PoseRelay
        self._generation += 1
        self._relay = PoseRelay()
        self._tracking = True
        self.request('tracking_start', self._generation)
        self._pose_timer.start()
        # Bind this session's relay, so a late old-stream callback cannot enter
        # the newly selected stream or mode.
        return self._relay.submit

    def end_tracking(self):
        self._tracking = False
        self._pose_timer.stop()
        self._relay = None
        self._generation += 1
        self.request('tracking_stop')

    def _send_pose(self):
        if not self._tracking or not self._ready or self._relay is None:
            return
        if self._process.bytesToWrite() > 65536:
            return  # Coalesce while the worker is slow; timestamps never renew.
        packet = self._relay.packet(self._generation)
        if packet is not None:
            self._process.write((json.dumps({'pose_packet': packet})+'\n').encode('utf-8'))

    def request(self, method, *args):
        if method not in METHODS:
            raise ValueError(method)
        if self._closing:
            return
        if self._tracking and method in {'set_ai_mode', 'set_ai_off', 'set_fov'}:
            raise RuntimeError('请先停止 SDK 跟随')
        # A slow device must not accumulate obsolete slider/selection changes.
        key = 'tracking' if method in {'set_ai_mode', 'set_ai_off', 'tracking_start', 'tracking_stop'} else method
        self._pending[key] = {'method': method, 'args': args}
        if self._process.state() == QProcess.NotRunning:
            self._ready = self._busy = False
            self._output.clear()
            self._process.start(self._command[0], self._command[1:])
        self._send_next()

    def _send_next(self):
        if not self._ready or self._busy or not self._pending or self._closing:
            return
        request = self._pending.pop(next(iter(self._pending)))
        if request['method'] == 'tracking_start':
            self._tracking_started = True
            self._stop_confirmed = False
        self._busy = True
        self._process.write((json.dumps(request)+'\n').encode('utf-8'))

    def _read(self):
        self._output.extend(bytes(self._process.readAllStandardOutput()))
        while b'\n' in self._output:
            line, _, rest = self._output.partition(b'\n')
            self._output = bytearray(rest)
            text = line.decode('utf-8', errors='replace')
            if not text.startswith(PREFIX):
                continue  # SDK native logs share stdout with the response protocol.
            reply = json.loads(text[len(PREFIX):])
            if 'tracking_log' in reply:
                self.tracking_event.emit(reply['tracking_log'])
            if reply.get('stopped'):
                self._stop_confirmed = True
            if 'error' in reply:
                if self._tracking:
                    self._tracking = False
                    self._pose_timer.stop()
                self.failed.emit(reply['error'])
            if reply.get('ready'):
                self._ready = True
            if 'method' in reply:
                self._busy = False
                if reply['method'] == 'tracking_stop' and reply['result'] == 0:
                    self._stop_confirmed = True
                self.completed.emit(reply['method'], reply['result'])
            self._send_next()
            if self._ready and not self._busy and not self._pending and not self._closing:
                self.idle.emit()

    def _error(self, _error):
        if not self._closing:
            self.failed.emit(self._process.errorString())

    def _finished(self, _code, _status):
        self._ready = self._busy = False
        self._pending.clear()
        if not self._closing:
            self.failed.emit('相机控制连接已断开，请重试')
        else:
            if self._tracking_started and not self._stop_confirmed:
                self.failed.emit('控制进程退出但未收到 SDK 停止应答，无法确认云台已停止')
            self.closed.emit()

    def close(self):
        self._closing = True
        self._tracking = False
        self._pose_timer.stop()
        self._pending.clear()
        self._process.closeWriteChannel()
        if self._process.state() == QProcess.NotRunning:
            self.closed.emit()
        else:
            QTimer.singleShot(3000, self._close_timeout)

    def _close_timeout(self):
        if self._process.state() != QProcess.NotRunning:
            self.failed.emit('SDK 未完成退出，无法确认云台已停止')
            self._process.kill()


def serve():
    from camera.tinyse_camera import TinySeCameraControl

    reply_lock = threading.Lock()
    def reply(value):
        with reply_lock:
            print('\n'+PREFIX+json.dumps(value, ensure_ascii=True), flush=True)

    control = TinySeCameraControl()
    runtime = None
    try:
        if not control.init():
            reply({'error': '未检测到 Tiny SE'})
            return 1
        reply({'ready': True})
        requests = queue.Queue()
        # Pose packets enter the bounded mailbox; only this serve thread calls SDK.
        def read_requests():
            try:
                for line in sys.stdin:
                    request = json.loads(line)
                    if 'pose_packet' in request:
                        if runtime is not None:
                            runtime.submit_packet(request['pose_packet'])
                    else:
                        requests.put(request)
            except Exception as exc:
                reply({'error': f'控制输入失败: {exc}'})
            finally:
                requests.put(None)
        reader = threading.Thread(target=read_requests, daemon=True)
        reader.start()
        while True:
            try:
                request = requests.get(timeout=.05)
            except queue.Empty:
                request = {}
            if request is None:
                break
            method = request.get('method')
            try:
                if method is not None and method not in METHODS:
                    raise ValueError(method)
                if method == 'tracking_start':
                    if runtime is None:
                        from camera.gimbal_control import GimbalSdk
                        from camera.tracking_runtime import TrackingRuntime
                        sdk = GimbalSdk.attach(control._dll, control._idx)
                        runtime = TrackingRuntime(sdk, lambda value: reply({'tracking_log': value}))
                    runtime.start(*request['args'])
                    result = 0
                elif method == 'tracking_stop':
                    if runtime is not None:
                        runtime.stop()
                    result = 0
                elif method is not None:
                    fn = getattr(control, method)
                    result = (runtime.setting(method, fn, *request['args']) if runtime
                              else fn(*request['args']))
                if method is not None:
                    reply({'method': method, 'result': result})
                if runtime is not None:
                    runtime.tick()
            except Exception as exc:
                if runtime is not None:
                    try:
                        runtime.stop()
                    except Exception as stop_exc:
                        reply({'error': f'停止无法确认: {stop_exc}'})
                value = {'error': str(exc)}
                if method is not None:
                    value.update(method=method, result=-1)
                reply(value)
    except Exception as exc:
        reply({'error': str(exc)})
        return 1
    finally:
        if runtime is not None:
            try:
                runtime.stop()
                reply({'stopped': True})
            except Exception as exc:
                reply({'error': f'停止无法确认: {exc}'})
        control.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(serve())
