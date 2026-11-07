"""Exercise the real Qt acquisition lifecycle with complete synthetic USB frames."""
import time

from qtpy.QtCore import QObject, Signal, Slot

from config.reaction_config import ReactionConfig
from hardware.beam_quality import BeamQualityPolicy
from hardware.sensor_frame import DeviceLayout, SensorFrame
from ui.measurement_controller import MeasurementController
from ui.reaction_controller import ReactionController


class Worker(QObject):
    sensor_frame_received = Signal(object)
    acquisition_issue = Signal(object)
    data_received = Signal(str)
    device_state_changed = Signal(str, str)
    layout_detected = Signal(object)

    def __init__(self, **kwargs):
        super().__init__()
        assert kwargs['legacy_frame_signals'] is False
        self.sample = 0
        self.layout = DeviceLayout.linear(1)
        self.stopped = False

    @Slot()
    def connect_device(self):
        self.device_state_changed.emit('connected', 'connected')

    @Slot()
    def prepare_walking_capture(self):
        self.layout_detected.emit(self.layout)

    @Slot()
    def stop(self):
        self.stopped = True
        self.device_state_changed.emit('disconnected', 'stopped')

    def frames(self, count, occupied=False):
        for _ in range(count):
            bits = bytes([int(occupied)] * 12 + [0] * 84)
            self.sensor_frame_received.emit(SensorFrame(
                'test-stream', self.layout, self.sample, self.sample, time.perf_counter_ns(),
                bits, b'\x01' * 96, b'\xff' * 12))
            self.sample += 1


def prepared(qtbot, controller):
    controller.quality_policy = BeamQualityPolicy(observation_seconds=1)
    controller.prepare(ReactionConfig(number_of_repetitions=1, ready_hold_ms=3,
                                     stimulus_delay_min_ms=10, stimulus_delay_max_ms=10))
    qtbot.waitUntil(lambda: controller.device_state == 'connected')
    local = controller._local if isinstance(controller, MeasurementController) else controller
    local._worker.frames(1000)
    qtbot.waitUntil(lambda: controller.walking_ready)
    controller.start()
    qtbot.waitUntil(lambda: controller.is_running)
    return local._worker


def test_real_controller_delivers_one_uncalibrated_report(qtbot):
    controller = MeasurementController(worker_factory=Worker)
    reports, requests = [], []
    controller.session_finished.connect(reports.append)
    controller.reaction_stimulus_requested.connect(requests.append)
    try:
        worker = prepared(qtbot, controller)
        assert isinstance(controller._local, ReactionController)
        worker.frames(4, occupied=True)
        qtbot.waitUntil(lambda: bool(requests))
        request = requests[0]
        controller.reaction_stimulus_presented({**request, 'success': True,
                                              'requested_monotonic_ns': time.perf_counter_ns()})
        qtbot.waitUntil(lambda: controller.engine.session.state == 'responding')
        worker.frames(11, occupied=False)
        qtbot.waitUntil(lambda: bool(reports))
        assert len(reports) == 1
        trial = reports[0].trials[0]
        assert trial.status == 'valid'
        assert trial.actual_stimulus_onset_ns is None
        assert trial.timing_quality == 'uncalibrated'
        assert trial.response_sample_index == 1004
        assert reports[0].finish_reason == 'completed'
        assert worker.stopped
        assert not controller.is_running
        assert controller.engine is None
    finally:
        controller.shutdown()


def test_stop_cancels_stimulus_and_preserves_attempt(qtbot):
    controller = ReactionController(worker_factory=Worker)
    reports, requests, cancelled = [], [], []
    controller.session_finished.connect(reports.append)
    controller.reaction_stimulus_requested.connect(requests.append)
    controller.reaction_stimulus_cancelled.connect(lambda: cancelled.append(True))
    try:
        worker = prepared(qtbot, controller)
        worker.frames(4, occupied=True)
        qtbot.waitUntil(lambda: bool(requests))
        cancelled.clear()
        controller.stop('manual')
        assert cancelled
        assert len(reports) == 1
        assert reports[0].trials[0].status == 'cancelled'
        controller.reaction_stimulus_presented({**requests[0], 'success': True,
                                              'requested_monotonic_ns': time.perf_counter_ns()})
        assert len(reports) == 1
    finally:
        controller.discard()


def test_stale_stimulus_token_and_disconnect_do_not_produce_valid_score(qtbot):
    controller = ReactionController(worker_factory=Worker)
    reports, requests = [], []
    controller.session_finished.connect(reports.append)
    controller.reaction_stimulus_requested.connect(requests.append)
    try:
        worker = prepared(qtbot, controller)
        worker.frames(4, occupied=True)
        qtbot.waitUntil(lambda: bool(requests))
        controller.reaction_stimulus_presented({**requests[0], 'session_id': 'previous-session',
                                              'success': True, 'requested_monotonic_ns': time.perf_counter_ns()})
        assert controller.engine.session.state == 'stimulus_pending'
        worker.device_state_changed.emit('error', 'unplugged')
        qtbot.waitUntil(lambda: bool(reports))
        assert reports[0].valid_count == 0
        assert reports[0].trials[0].status == 'gap'
        assert reports[0].finish_reason == 'error'
    finally:
        controller.discard()


def test_new_session_ignores_previous_generation_callbacks(qtbot):
    controller = ReactionController(worker_factory=Worker)
    reports, requests = [], []
    controller.session_finished.connect(reports.append)
    controller.reaction_stimulus_requested.connect(requests.append)
    try:
        worker = prepared(qtbot, controller)
        worker.frames(4, occupied=True)
        qtbot.waitUntil(lambda: bool(requests))
        old_request = requests[-1]
        controller.stop('manual')
        worker = prepared(qtbot, controller)
        worker.frames(4, occupied=True)
        qtbot.waitUntil(lambda: len(requests) == 2)
        assert requests[-1]['session_id'] != old_request['session_id']
        controller._on_reaction_finished('completed', old_request['session_id'])
        controller._on_reaction_armed(old_request['session_id'])
        controller.reaction_stimulus_presented({**old_request, 'success': True,
                                              'requested_monotonic_ns': time.perf_counter_ns()})
        assert controller.is_running
        assert len(reports) == 1
        assert controller.engine.session.state == 'stimulus_pending'
        controller.stop('manual')
        assert len(reports) == 2
    finally:
        controller.discard()
