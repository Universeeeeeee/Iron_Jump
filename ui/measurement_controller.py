"""Use the verified child for walking; retain existing controllers for other modes."""
from datetime import datetime
from pathlib import Path
import uuid
from qtpy.QtCore import QObject, Signal
from hardware.beam_quality import BeamQualityPolicy
from path_utils import get_base_dir
from ui.session_controller import SessionController
from ui.measurement_process.client import ProcessSession

SIGNALS = ('hop_event', 'jump_quality_notice', 'gait_step_event', 'gait_snapshot',
           'footprint_visual_frame', 'device_message', 'device_state_changed', 'device_layout_changed',
           'walking_readiness_changed', 'led_health_changed', 'beam_quality_notice',
           'pause_state_changed', 'session_started', 'session_finished')


class MeasurementController(QObject):
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

    def __init__(self, parent=None, *, worker_factory=None, evidence_root=None):
        super().__init__(parent)
        self._local = SessionController(self, worker_factory=worker_factory)
        self._child = None
        self._worker_factory = worker_factory
        self._config = None
        self.quality_policy = BeamQualityPolicy()
        self.evidence_root = Path(evidence_root or Path(get_base_dir()) / 'data/capture_logs/measurements')
        self._bind(self._local)

    def _bind(self, controller):
        for name in SIGNALS:
            getattr(controller, name).connect(getattr(self, name))

    @property
    def is_running(self):
        return self._child.is_running if self._child else self._local.is_running

    @property
    def is_paused(self):
        return False if self._child else self._local.is_paused

    @property
    def _start_pending(self):
        return self._child._start_pending if self._child else self._local._start_pending

    @property
    def quality_status(self):
        return self._child.quality_status if self._child else self._local.quality_status

    @property
    def device_state(self):
        return self._child.device_state if self._child else self._local.device_state

    @property
    def engine(self):
        return None if self._child else self._local.engine

    @property
    def config(self):
        return self._config

    @property
    def quality_preflight_required(self):
        return self._child is not None or self._local._quality is not None

    @property
    def has_prepared_session(self):
        return self._child is not None or self._local.engine is not None

    def prepare(self, config):
        if self._child:
            self._child.close_and_wait()
        self._config = config
        if config.test_type == 'Sprint and Gait Test':
            self._local.discard()
            folder = self.evidence_root / (datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8])
            child = ProcessSession(folder, self, worker_factory=self._worker_factory)
            child.quality_policy = self.quality_policy
            self._child = child
            self._bind(child)
            child.closed.connect(self._on_closed)
            child.prepare(config)
        else:
            self._local.quality_policy = self.quality_policy
            self._local.prepare(config)

    def _on_closed(self, _status):
        child, self._child = self._child, None
        child.deleteLater()

    def start(self, **kwargs):
        return (self._child or self._local).start(**kwargs)

    def stop(self, reason=None):
        if self._child:
            self._child.control('stop', reason=reason or 'manual')
        else:
            self._local.stop(reason)

    def discard(self):
        if self._child:
            self._child.close_and_wait()
        self._local.discard()
        self._config = None

    def shutdown(self):
        if self._child:
            self._child.close_and_wait()
        elif self._local.is_running:
            self._local.stop('manual')
        else:
            self._local.discard()

    def ensure_device_connected(self):
        if self._child is None:
            self._local.ensure_device_connected()

    def retry_device(self):
        if self._child:
            self._child._send('retry_device')
        else:
            self._local.retry_device()

    def refresh_led_health(self):
        if self._child:
            self._child._send('refresh_led_health')
        else:
            self._local.refresh_led_health()

    def toggle_pause(self):
        if self._child is None:
            self._local.toggle_pause()
