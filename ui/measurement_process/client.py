"""GUI-thread facade with bounded IPC and confirmed process completion."""
from dataclasses import asdict
import json
import multiprocessing
import pickle
from pathlib import Path
import threading
from qtpy.QtCore import QObject, QTimer, Signal, QEventLoop
from .actor import run_actor
from .artifacts import load_report
from .inbox import Inbox
from .outbox import Outbox
from .protocol import OUTPUTS, validate


class ProcessSession(QObject):
    hop_event = Signal(object)
    jump_quality_notice = Signal(dict)
    gait_step_event = Signal(object)
    gait_snapshot = Signal(dict)
    footprint_visual_frame = Signal(dict)
    device_message = Signal(str)
    device_state_changed = Signal(str, str)
    device_layout_changed = Signal(object)
    walking_readiness_changed = Signal(dict)
    led_health_changed = Signal(dict)
    beam_quality_notice = Signal(dict)
    pause_state_changed = Signal(bool)
    session_started = Signal()
    session_finished = Signal(object)
    closed = Signal(dict)
    failed = Signal(str)

    def __init__(self, folder, parent=None, *, worker_factory=None):
        super().__init__(parent)
        self.folder = Path(folder)
        self.worker_factory = worker_factory
        self.process = self.connection = self.writer = self.reader = None
        self.inbox = Inbox()
        self.timer = QTimer(self)
        self.timer.setInterval(5)
        self.timer.timeout.connect(self._tick)
        self.sequence = self.command_sequence = 0
        self.report = self.terminal = None
        self.errors = []
        self.is_running = self._start_pending = self._control_pending = False
        self.device_state = 'disconnected'
        self.quality_status = {}
        self.quality_policy = None
        self.complete = False

    def _send(self, kind, **values):
        self.command_sequence += 1
        self.writer.enqueue(dict(sequence=self.command_sequence, kind=kind, **values))

    def prepare(self, config):
        if self.process is not None:
            raise RuntimeError('A process session cannot be reused')
        self.folder.mkdir(parents=True, exist_ok=False)
        (self.folder / 'active.lock').mkdir()
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=run_actor,
            args=(child, str(self.folder / 'actor'), self.worker_factory))
        self.process.start()
        child.close()
        self.writer = Outbox(self.connection)
        self.reader = threading.Thread(target=self._receive, name='MeasurementReceiver', daemon=True)
        self.reader.start()
        self.config = config
        self.device_state = 'connecting'
        self.device_state_changed.emit('connecting', '正在准备独立测量会话…')
        self.timer.start()

    def _receive(self):
        detail = None
        try:
            while not self.inbox.closed:
                if not self.connection.poll(.2):
                    continue
                if not self.inbox.put(self.connection.recv_bytes(self.inbox.max_bytes)):
                    break
        except (EOFError, OSError, ValueError) as exc:
            detail = repr(exc)
        finally:
            self.inbox.ended(detail)

    def _packet(self, message):
        self.sequence = validate(message, self.sequence, OUTPUTS, self.process.pid)
        kind, value = message['kind'], message['payload']
        if kind == 'actor_ready':
            self._send('prepare', config=self.config.to_dict(), quality_policy=asdict(self.quality_policy))
        elif kind == 'readiness':
            self.quality_status = value
            if value.get('start_rejected'):
                self._start_pending = False
            self.walking_readiness_changed.emit(value)
        elif kind == 'snapshot':
            self.gait_snapshot.emit(value)
        elif kind == 'visual':
            self.footprint_visual_frame.emit(value)
        elif kind == 'notification':
            name, args = value['signal'], value['args']
            if name == 'device_state_changed':
                self.device_state = args[0]
            getattr(self, name).emit(*args)
        elif kind == 'started':
            self._start_pending = False
            self.is_running = True
            self.session_started.emit()
        elif kind == 'command_completed':
            self.is_running = self._start_pending = False
        elif kind == 'report':
            self.report = load_report(self.folder / 'actor', value)
        elif kind == 'terminal':
            self.terminal = value

    def _tick(self):
        try:
            for packet in self.inbox.take(16):
                self._packet(pickle.loads(packet))
            snapshot = self.inbox.snapshot()
            if self.terminal is None:
                if not self.process.is_alive() and snapshot['reader_done'] and not snapshot['queued_messages']:
                    raise RuntimeError('Measurement process exited without completion')
                return
            if self.process.is_alive() or not snapshot['reader_done'] or snapshot['queued_messages']:
                return
            self.process.join(0)
            writer_stopped = self.writer.finish(5)
            self.inbox.close()
            self.connection.close()
            self.reader.join(1)
            self.timer.stop()
            self.complete = (self.terminal['complete'] and not self.terminal['errors']
                             and self.process.exitcode == 0 and writer_stopped and not self.reader.is_alive()
                             and (not self.terminal['report_expected'] or self.report is not None))
            status = dict(complete=self.complete, actor_pid=self.process.pid, actor_exitcode=self.process.exitcode,
                          commands=self.command_sequence, outputs=self.sequence, report_received=self.report is not None)
            (self.folder / 'status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
            if not self.complete:
                raise RuntimeError('Measurement cleanup/report not confirmed: ' + repr(self.terminal['errors']))
            if self.report is not None:
                self.session_finished.emit(self.report)
            self.closed.emit(status)
        except BaseException as exc:
            self._fail(repr(exc))

    def start(self, *, acknowledge_quality=False, quality_key=None):
        if self.is_running or self._start_pending or not self.quality_status.get('ready'):
            return False
        self._start_pending = True
        self._send('start', acknowledge_quality=acknowledge_quality, quality_key=quality_key or self.quality_status['device_key'])
        return True

    def control(self, kind, **values):
        if self._control_pending:
            return
        self._control_pending = True
        self._send(kind, **values)

    def close_and_wait(self, timeout_ms=30000):
        if self.complete:
            return
        if not self.errors:
            self.control('close')
            loop = QEventLoop()
            self.closed.connect(loop.quit)
            self.failed.connect(loop.quit)
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            timeout.start(timeout_ms)
            loop.exec()
            timeout.stop()
        if self.errors:
            self.process.join(5)
        if not self.complete:
            raise RuntimeError('Measurement close unconfirmed; evidence and lock retained at ' + str(self.folder))

    def _fail(self, error):
        if self.errors:
            return
        self.errors.append(error)
        self.timer.stop()
        self.inbox.close()
        self.writer.abort('GUI_failure')
        self.writer.finish(1)
        self.connection.close()
        self.device_state = 'error'
        (self.folder / 'failure.json').write_text(json.dumps(dict(error=error,
            actor_pid=self.process.pid, actor_alive=self.process.is_alive()), indent=2), encoding='utf-8')
        self.device_state_changed.emit('error', '测量会话未完成，请保留记录并检查设备。')
        self.failed.emit(error)
