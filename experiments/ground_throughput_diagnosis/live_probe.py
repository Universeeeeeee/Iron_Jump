"""Observation only: original NumPy, bounded sampled synchronous call trees."""
import argparse
import functools
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import runpy
import sys
import threading
import time
import ctypes

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / 'experiments/runtime_single_frame_fusion'
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--level', choices=('M', 'D'), required=True)
parser.add_argument('--sample-offset', type=int, default=0)
options, remaining = parser.parse_known_args()
sys.argv = [str(HERE / 'live_replay.py')] + remaining
out = Path(remaining[remaining.index('--output') + 1])
mode = remaining[remaining.index('--mode') + 1]
diagnostic = options.level == 'D'
# PyDLL keeps the GIL during this tiny OS query; WinDLL would itself add GIL handoffs.
kernel = ctypes.PyDLL('kernel32') if sys.platform == 'win32' else None
if kernel:
    kernel.QueryThreadCycleTime.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64))
    kernel.QueryThreadCycleTime.restype = ctypes.c_int
def cycles():
    value = ctypes.c_uint64()
    if kernel:
        assert kernel.QueryThreadCycleTime(ctypes.c_void_p(-2), ctypes.byref(value))
    return value.value
controllers = []
batches, drains, spans, qt_events, gui_spans, ticks = [], [], [], [], [], []
milestones = []
local = threading.local()
final_state = {}
source_clock = {}
thread_ids = {'gui': threading.get_native_id()}

from engine.device_quality_session import DeviceQualitySession
from engine.overground_session import OvergroundSession
from hardware.walking_preflight import RuntimeBeamEvidence
from hardware.beam_filter import GroundStabilityFilter
from hardware.payload_mirror import PeriodicPayloadMirrorGuard
from engine.gait_engine import GaitEngine
from ui.session_controller import SessionController, _GroundFrameInbox

assert RuntimeBeamEvidence.__module__ == 'hardware.walking_preflight'
assert DeviceQualitySession.on_frame.__code__.co_filename.endswith('device_quality_session.py')
assert importlib.import_module('engine.device_quality_session').RuntimeBeamEvidence is RuntimeBeamEvidence

original_init = SessionController.__init__
def init(self, *a, **kw):
    original_init(self, *a, **kw)
    controllers.append(self)
SessionController.__init__ = init

# The identical finite replay boundary used in the accepted parent experiment.
for cls in (DeviceQualitySession, OvergroundSession):
    original_poll = cls.poll
    def finite_poll(self, _poll=original_poll):
        worker = controllers[-1]._worker if controllers else None
        if worker is not None and getattr(worker, 'exhausted_ns', None) is not None:
            return
        return _poll(self)
    cls.poll = finite_poll

original_consume = _GroundFrameInbox._consume
def consume(self, items):
    if diagnostic:
        start = time.perf_counter_ns()
        cpu = time.thread_time_ns()
        cycle_start = cycles()
    original_consume(self, items)
    if items:
        frame = next((value for issue, value in reversed(items) if not issue), None)
        if frame is not None:
            self.probe_last_sample = frame.sample_index
            self.probe_count = getattr(self, 'probe_count', 0) + len(items)
            end = time.perf_counter_ns()
            milestones.append((end, frame.sample_index, frame.received_monotonic_ns, len(items)))
            if 'consumer' not in thread_ids:
                thread_ids['consumer'] = threading.get_native_id()
            if diagnostic:
                cpu_elapsed = time.thread_time_ns() - cpu
                first = next(value for issue, value in items if not issue)
                batches.append((start, end, cpu_elapsed, len(items), first.sample_index,
                                frame.sample_index, first.received_monotonic_ns,
                                frame.received_monotonic_ns, cycles() - cycle_start))
_GroundFrameInbox._consume = consume

original_drain = _GroundFrameInbox.drain
def drain(self):
    start, cpu = time.perf_counter_ns(), time.thread_time_ns()
    cycle_start = cycles()
    with self._lock:
        count = len(self._pending)
        oldest = self._pending[0][1].received_monotonic_ns if count else None
    before = len(batches)
    interval = self._timer.interval()
    original_drain(self)
    with self._lock:
        after_count = len(self._pending)
    drains.append((start, time.perf_counter_ns(), time.thread_time_ns() - cpu,
                   count, after_count, oldest, interval, before, len(batches),
                   self._timer.interval(), cycle_start, cycles()))
if diagnostic:
    _GroundFrameInbox.drain = drain

from qtpy.QtCore import QAbstractEventDispatcher
original_monitor = _GroundFrameInbox.monitor
def monitor(self):
    thread_ids['measurement'] = threading.get_native_id()
    if diagnostic:
        dispatcher = QAbstractEventDispatcher.instance()
        dispatcher.awake.connect(lambda: qt_events.append(('awake', time.perf_counter_ns())))
        dispatcher.aboutToBlock.connect(lambda: qt_events.append(('block', time.perf_counter_ns())))
    original_monitor(self)
_GroundFrameInbox.monitor = monitor

def call(label, function, args, kwargs):
    stack = local.stack
    parent = stack[-1] if stack else None
    node = [len(spans), label, parent[0] if parent else None, local.sample,
            time.perf_counter_ns(), time.thread_time_ns(), 0, 0, cycles(), 0]
    spans.append(None)
    stack.append(node)
    try:
        return function(*args, **kwargs)
    finally:
        end, cpu = time.perf_counter_ns(), time.thread_time_ns()
        cycle_end = cycles()
        stack.pop()
        wall_elapsed, cpu_elapsed = end - node[4], cpu - node[5]
        spans[node[0]] = (node[0], label, node[2], node[3], node[4], end,
                          cpu_elapsed, wall_elapsed - node[6], cpu_elapsed - node[7],
                          cycle_end - node[8], cycle_end - node[8] - node[9])
        if parent:
            parent[6] += wall_elapsed
            parent[7] += cpu_elapsed
            parent[9] += cycle_end - node[8]

original_quality = DeviceQualitySession.on_frame
def quality(self, frame):
    if self.context is None or (frame.sample_index - options.sample_offset) % 64:
        return original_quality(self, frame)
    local.stack, local.sample, local.active = [], frame.sample_index, True
    try:
        return call('quality', original_quality, (self, frame), {})
    finally:
        local.active = False
if diagnostic:
    DeviceQualitySession.on_frame = quality

def wrap(cls, name, label):
    original = getattr(cls, name)
    @functools.wraps(original)
    def measured(*args, **kwargs):
        if not getattr(local, 'active', False):
            return original(*args, **kwargs)
        return call(label, original, args, kwargs)
    setattr(cls, name, measured)

if diagnostic:
    for cls, name, label in (
        (RuntimeBeamEvidence, 'observe', 'runtime_evidence'),
        (GaitEngine, 'process_quality_frame', 'engine_forward'),
        (OvergroundSession, 'on_frame', 'session'),
        (OvergroundSession, 'archive_raw_frame', 'raw_archive'),
        (OvergroundSession, '_consume_frames', 'filtered_consume'),
        (OvergroundSession, 'publish_snapshot', 'snapshot'),
        (OvergroundSession, 'publish_visual', 'visual_emit'),
        (GroundStabilityFilter, 'feed', 'filter'),
        (GroundStabilityFilter, '_feed', 'filter_numeric'),
        (GroundStabilityFilter, '_render', 'filter_render'),
        (PeriodicPayloadMirrorGuard, 'feed', 'mirror_guard'),
    ):
        # Keep static method binding intact.
        if name == '_render':
            original_render = cls._render
            def render(item):
                if not getattr(local, 'active', False):
                    return original_render(item)
                return call('filter_render', original_render, (item,), {})
            cls._render = staticmethod(render)
        else:
            wrap(cls, name, label)
    from engine.modes.walking_processor import WalkingProcessor
    from engine.modes.overground_running_processor import OvergroundRunningProcessor
    for cls in (WalkingProcessor, OvergroundRunningProcessor):
        for name, label in (
            ('process', 'processor'), ('_observe_ownership_groups', 'ownership'),
            ('_recover_ownership_groups', 'ownership_recover'),
            ('_commit_contacts', 'commit'), ('_sync_touch_publications', 'publications'),
            ('_record_visual', 'record_visual'), ('summary', 'summary'),
        ):
            wrap(cls, name, label)
        name = '_clusters' if cls is WalkingProcessor else '_groups'
        wrap(cls, name, 'clusters')

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def evidence(quality, session):
    runtime = quality._runtime
    window = hashlib.sha256()
    for bits, changes in runtime._window:
        window.update(bits.tobytes())
        window.update(changes.tobytes())
    return {
        'runtime_counts': runtime._counts.tolist(),
        'runtime_transitions': runtime._transitions.tolist(),
        'runtime_healthy_samples': runtime.healthy_samples,
        'runtime_window_sha256': window.hexdigest(),
        'quality': quality.snapshot(),
        'processor_audit_sha256': digest(session.processor.event_audit),
        'touch_events': session.processor.touch_events,
        'timeline_sha256': digest(list(session.processor.timeline)),
        'mirror_events': session._frame_filter.mirror_guard.events,
    }

original_build = OvergroundSession.build_report
def build_report(self, reason):
    result = original_build(self, reason)
    final_state.update(evidence(controllers[-1]._quality, self))
    worker = controllers[-1]._worker
    if worker is not None and hasattr(worker, 'anchor_ns'):
        source_clock.update(anchor_ns=worker.anchor_ns, arm_pause_ns=worker.arm_pause_ns,
                            source_start_sample=int(worker.indices[0]),
                            source_end_sample=int(worker.indices[-1]))
    return result
OvergroundSession.build_report = build_report

if diagnostic:
    from ui.embedded_camera_panel import EmbeddedCameraPanel
    from ui.annotation_canvas import AnnotationCanvas
    from ui.ground_track import GroundChannelWidget
    from ui.views.execution_view import ExecutionView
    from vision.live_walking import _PreviewAdapter
    def gui_wrap(cls, name, label):
        original = getattr(cls, name)
        def measured(*a, **kw):
            start, cpu = time.perf_counter_ns(), time.thread_time_ns()
            try:
                return original(*a, **kw)
            finally:
                gui_spans.append((label, start, time.perf_counter_ns(), time.thread_time_ns() - cpu,
                                  threading.get_native_id()))
        setattr(cls, name, measured)
    for cls, name, label in (
        (EmbeddedCameraPanel, '_render_frame', 'preview'),
        (AnnotationCanvas, 'paintEvent', 'preview_paint'),
        (GroundChannelWidget, 'paintEvent', 'track_paint'),
        (ExecutionView, 'on_footprint_visual_frame', 'visual_slot'),
        (_PreviewAdapter, 'infer_bgr', 'inference'),
    ):
        gui_wrap(cls, name, label)

import qtpy.QtWidgets as widgets
from qtpy.QtCore import QTimer
BaseApp = widgets.QApplication
class App(BaseApp):
    def __init__(self, *a):
        super().__init__(*a)
        # M/D share only the PID marker; no disk writes during active processing.
        (out / 'pid.json').write_text(json.dumps({'pid': os.getpid(), 'host_ns': time.perf_counter_ns()}))
        if diagnostic:
            self.probe_timer = QTimer(self)
            self.probe_timer.setInterval(10)
            self.probe_timer.timeout.connect(lambda: ticks.append(time.perf_counter_ns()))
            self.probe_timer.start()
widgets.QApplication = App

try:
    runpy.run_path(str(HERE / 'live_replay.py'), run_name='__main__')
finally:
    if out.exists():
        import numpy
        import qtpy
        manifest = json.loads((OLD / 'baseline_manifest.json').read_text())['base_files']
        data = {
            'level': options.level, 'mode': mode, 'sample_offset': options.sample_offset,
            'sample_modulus': 64, 'milestones': milestones,
            'batches': batches, 'drains': drains, 'spans': spans,
            'qt_events': qt_events, 'gui_spans': gui_spans, 'ticks': ticks,
            'thread_ids': thread_ids, 'final_state': final_state, 'source_clock': source_clock,
            'environment': {'python': sys.version, 'platform': platform.platform(),
                            'numpy': numpy.__version__, 'qt': qtpy.QT_VERSION,
                            'thread_clock': str(time.get_clock_info('thread_time')),
                            'cycle_clock': 'QueryThreadCycleTime via PyDLL; raw cycles, not converted to time',
                            'cpu_clock_limitation': 'GetThreadTimes observed increments 15.625ms despite declared 100ns; per-call CPU attribution unusable'},
            'baseline_hashes': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                for name in manifest},
            'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        (out / 'diagnostic.json').write_text(json.dumps(data), encoding='utf-8')
