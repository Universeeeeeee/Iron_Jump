"""Single-thread reaction trials over complete USB samples, without camera input."""
import time
import uuid

from qtpy.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot

from hardware.known_beams import load_known_beams
from hardware.walking_preflight import WalkingPreflight
from ui.session_controller import SessionController


class ReactionBridge(QObject):
    readiness = Signal(dict)
    armed = Signal(str)
    snapshot = Signal(dict)
    stimulus_requested = Signal(dict)
    stimulus_cancelled = Signal(str)
    finished = Signal(str, str)
    overground = None

    def __init__(self, config, policy, session_id):
        super().__init__()
        from engine.reaction_session import ReactionSession
        self.session = ReactionSession(config)
        self.config = config
        self.session_id = session_id
        self.preflight = WalkingPreflight(policy, known_bad_beams=load_known_beams())
        self.running = False
        self._paused = True
        self._finished = False
        self._last_publish = 0
        self._last_snapshot = None
        self._armed_context = None
        self._armed_ns = None
        self._stop_timer = QTimer(self)
        self._stop_timer.setTimerType(Qt.PreciseTimer)
        self._stop_timer.setInterval(10)
        self._stop_timer.timeout.connect(self.poll)

    @Slot()
    def monitor(self):
        self._stop_timer.start()
        self.poll()

    def _readiness(self):
        result = self.preflight.status(time.perf_counter_ns())
        result['_reaction_session_id'] = self.session_id
        if result['segment_count'] not in (None, 1):
            result.update(ready=False, message='反应时测试需要单段设备')
        if result['bad_indices']:
            result.update(ready=False, requires_acknowledgement=False,
                          message='请清空测量区域并排除异常光束后开始反应时测试')
        return result

    @Slot(object)
    def arm_checked(self, request):
        if self.running or self._finished:
            return
        status = self._readiness()
        if not status['ready'] or request[0] != status['device_key']:
            status.update(start_rejected=True)
            self.readiness.emit(status)
            return
        self.running = True
        self._paused = False
        self._armed_context = self.preflight.context
        self._armed_ns = time.perf_counter_ns()
        self.armed.emit(self.session_id)
        self._deliver(self.session.begin(self._armed_ns))
        self._publish(force=True)

    @Slot(object)
    def on_frame(self, frame):
        if self._finished:
            return
        if self.running:
            if frame.received_monotonic_ns < self._armed_ns:
                return
            if (frame.stream_id != self._armed_context.stream_id
                    or frame.layout != self._armed_context.layout):
                self._deliver(self.session.on_issue('device_changed', time.perf_counter_ns()))
                return
            self._deliver(self.session.on_frame(frame))
            self._publish()
        else:
            self.preflight.feed(frame)

    @Slot(object)
    def on_issue(self, issue):
        if self._finished:
            return
        code = getattr(issue, 'code', str(issue))
        if self.running:
            self._deliver(self.session.on_issue(code, time.perf_counter_ns()))
            self._publish(force=True)
        else:
            self.preflight.invalidate('采集异常，请重新完成空场自检')

    @Slot(str, str)
    def on_device_state(self, state, message):
        if self._finished or state not in {'disconnected', 'error'}:
            return
        if self.running:
            self._deliver(self.session.on_issue('disconnected', time.perf_counter_ns()))
            if not self._finished:
                self.halt()
                self.finished.emit('error', self.session_id)
        else:
            self.preflight.invalidate(message)

    @Slot(dict)
    def acknowledge_stimulus(self, value):
        if not self.running or self._finished:
            return
        self._deliver(self.session.acknowledge_stimulus(
            value['trial_index'], value['requested_monotonic_ns'],
            value['stimulus_type'], success=value.get('success', False)))
        self._publish(force=True)

    @Slot()
    def next_trial(self):
        if self.running and not self._finished:
            self._deliver(self.session.next_trial(time.perf_counter_ns()))
            self._publish(force=True)

    @Slot()
    def poll(self):
        if self._finished:
            return
        if self.running:
            self._deliver(self.session.poll(time.perf_counter_ns()))
            self._publish()
        else:
            now = time.perf_counter_ns()
            if now - self._last_publish >= 100_000_000:
                self._last_publish = now
                self.readiness.emit(self._readiness())

    def _publish(self, force=False):
        value = self.session.snapshot()
        value['_reaction_session_id'] = self.session_id
        now = time.perf_counter_ns()
        if force or value != self._last_snapshot or now - self._last_publish >= 100_000_000:
            self._last_snapshot = value
            self._last_publish = now
            self.snapshot.emit(value)

    def _deliver(self, events):
        for event in events:
            if event.kind == 'stimulus_requested':
                self.stimulus_requested.emit(dict(trial_index=event.trial_index,
                                                  stimulus_type=event.modality,
                                                  session_id=self.session_id))
            if event.record is not None:
                self.stimulus_cancelled.emit(self.session_id)
        if self.session.is_finished and not self._finished:
            self._finished = True
            self._stop_timer.stop()
            self.stimulus_cancelled.emit(self.session_id)
            self._publish(force=True)
            self.finished.emit(self.session.build_report().finish_reason, self.session_id)

    @Slot()
    def halt(self):
        self._stop_timer.stop()
        if self.running and not self.session.is_finished:
            self.session.cancel(time.perf_counter_ns())
        self._finished = True
        self.stimulus_cancelled.emit(self.session_id)

    def build_report(self, reason='manual'):
        return self.session.build_report(reason)


class ReactionController(SessionController):
    reaction_snapshot = Signal(dict)
    reaction_stimulus_requested = Signal(dict)
    reaction_stimulus_cancelled = Signal()
    stimulus_presented_requested = Signal(dict)
    next_trial_requested = Signal()

    def prepare(self, config):
        self._cleanup()
        self._reaction_session_id = uuid.uuid4().hex
        self._config = config
        self._finish_reason = None
        self._thread = QThread()
        self._worker = self._worker_factory(
            dll_path=self._dll_path, vid=self._vid, pid=self._pid,
            timeout_ms=self._timeout_ms, chunk_size=self._chunk_size,
            legacy_frame_signals=False)
        if not all(hasattr(self._worker, name) for name in
                   ('sensor_frame_received', 'acquisition_issue', 'prepare_walking_capture')):
            self._worker = self._thread = None
            raise ValueError('反应时测试需要带设备样本编号的完整光条数据')
        self._worker.moveToThread(self._thread)
        self._engine = self._quality = bridge = ReactionBridge(
            config, self.quality_policy, self._reaction_session_id)
        bridge.moveToThread(self._thread)
        self._worker.sensor_frame_received.connect(bridge.on_frame, Qt.QueuedConnection)
        self._worker.acquisition_issue.connect(bridge.on_issue, Qt.QueuedConnection)
        self._worker.device_state_changed.connect(bridge.on_device_state)
        self._worker.device_state_changed.connect(self._on_device_state)
        self._worker.data_received.connect(self._on_device_message)
        self._worker.layout_detected.connect(self._on_device_layout)
        if hasattr(self._worker, 'led_health_changed'):
            self._worker.led_health_changed.connect(self._on_led_health)
        self.connect_device_requested.connect(self._worker.connect_device)
        self.prepare_walking_requested.connect(self._worker.prepare_walking_capture)
        self.prepare_walking_requested.connect(bridge.monitor)
        self.ground_start_requested.connect(bridge.arm_checked)
        self.stimulus_presented_requested.connect(bridge.acknowledge_stimulus)
        self.next_trial_requested.connect(bridge.next_trial)
        bridge.readiness.connect(self._on_walking_readiness)
        bridge.armed.connect(self._on_reaction_armed)
        bridge.snapshot.connect(self._on_reaction_snapshot)
        bridge.stimulus_requested.connect(self._forward_stimulus)
        bridge.stimulus_cancelled.connect(self._on_reaction_cancelled)
        bridge.finished.connect(self._on_reaction_finished)
        self._thread.started.connect(self._worker.connect_device)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(bridge.deleteLater)
        self._device_state = 'connecting'
        self.device_state_changed.emit('connecting', '正在连接设备...')
        self._thread.start()

    @Slot(dict)
    def _forward_stimulus(self, value):
        if self._is_running and value['session_id'] == self._reaction_session_id:
            self.reaction_stimulus_requested.emit(value)

    @Slot(dict)
    def _on_walking_readiness(self, value):
        if self._engine is not None and value['_reaction_session_id'] == self._reaction_session_id:
            super()._on_walking_readiness(value)

    @Slot(str, str)
    def _on_reaction_finished(self, reason, session_id):
        if session_id == self._reaction_session_id:
            super()._on_engine_finished(reason)

    @Slot(str)
    def _on_reaction_armed(self, session_id):
        if self._engine is not None and session_id == self._reaction_session_id:
            super()._on_walking_armed()

    @Slot(dict)
    def _on_reaction_snapshot(self, value):
        if self._engine is not None and value['_reaction_session_id'] == self._reaction_session_id:
            self.reaction_snapshot.emit(value)

    @Slot(str)
    def _on_reaction_cancelled(self, session_id):
        if session_id == self._reaction_session_id:
            self.reaction_stimulus_cancelled.emit()

    def reaction_stimulus_presented(self, value):
        if self._is_running and value.get('session_id') == self._reaction_session_id:
            self.stimulus_presented_requested.emit(value)

    def reaction_next(self):
        if self._is_running:
            self.next_trial_requested.emit()

    def pause(self):
        pass  # A trial is stopped, never paused across a stimulus.

    def resume(self):
        pass

    def _do_stop(self, reason):
        self.reaction_stimulus_cancelled.emit()
        return super()._do_stop(reason)

    def _cleanup(self):
        self.reaction_stimulus_cancelled.emit()
        super()._cleanup()
