"""External-profile-only GUI delivery evidence; no baseline latency claims."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
import threading
import time
import ctypes

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
state_index = sys.argv.index('--preview-state')
preview_state = sys.argv[state_index + 1]
del sys.argv[state_index:state_index + 2]
assert preview_state in ('enabled', 'disabled')
out = Path(sys.argv[sys.argv.index('--output') + 1])
switches = []
initial_switch = sys.getswitchinterval()
original_set_switch = sys.setswitchinterval
def set_switch(value):
    result = original_set_switch(value)
    switches.append((time.perf_counter_ns(), sys.getswitchinterval()))
    return result
sys.setswitchinterval = set_switch

kernel = ctypes.PyDLL('kernel32')
kernel.QueryThreadCycleTime.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64))
kernel.QueryThreadCycleTime.restype = ctypes.c_int
def cycles():
    value = ctypes.c_uint64()
    assert kernel.QueryThreadCycleTime(ctypes.c_void_p(-2), ctypes.byref(value))
    return value.value

# Exact low-frequency counts corroborate rare events in the 1/64 observer.
from engine.overground_session import OvergroundSession
from engine.modes.walking_processor import WalkingProcessor
from engine.modes.overground_running_processor import OvergroundRunningProcessor
low_spans = []
def low_wrap(cls, method, label):
    original = getattr(cls, method)
    def measured(self, *a, **kw):
        frame = getattr(self, '_last_frame', None)
        sample = frame.sample_index if frame is not None else getattr(self, 'last_sample', -1)
        start, c = time.perf_counter_ns(), cycles()
        try:
            return original(self, *a, **kw)
        finally:
            low_spans.append((label, start, time.perf_counter_ns(), cycles() - c,
                              sample, threading.get_native_id()))
    setattr(cls, method, measured)
for cls in (WalkingProcessor, OvergroundRunningProcessor):
    low_wrap(cls, 'summary', 'summary')
low_wrap(OvergroundSession, 'publish_snapshot', 'snapshot')
low_wrap(OvergroundSession, 'publish_visual', 'visual_emit')

from qtpy.QtCore import QTimer
from ui.annotation_canvas import AnnotationCanvas
original_draw = AnnotationCanvas._draw_live_pose
draws = []
captured = False
def draw(self, painter, rect):
    global captured
    overlay = self._live_pose[0]
    nodes = overlay['nodes']
    links = sum(nodes[a]['valid'] and nodes[b]['valid'] for a, b in overlay['connections'])
    before = time.perf_counter_ns()
    result = original_draw(self, painter, rect)
    draws.append((before, time.perf_counter_ns(), links,
                  sum(node['valid'] for node in nodes.values()), threading.get_native_id(), bool(self.isEnabled())))
    if links and not captured:
        captured = True
        def save():
            self.window().grab().save(str(out / 'live_overlay.png'))
        QTimer.singleShot(0, save)
    return result
AnnotationCanvas._draw_live_pose = draw

try:
    runpy.run_path(str(HERE / ('enabled_probe.py' if preview_state == 'enabled' else 'probe.py')), run_name='__main__')
finally:
    if out.exists():
        data = {'preview_state': preview_state,
                'system_exit_code': getattr(sys.exc_info()[1], 'code', None),
                'draws': draws, 'captured_live_overlay': captured,
                'low_frequency_spans': low_spans,
                'initial_switch_interval_seconds': initial_switch,
                'final_switch_interval_seconds': sys.getswitchinterval(),
                'switch_changes': switches,
                'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'scope': 'Only external profiler rounds. First live-overlay screenshot triggers extra painting; these rounds are excluded from baseline performance calibration.'}
        (out / 'external_delivery.json').write_text(json.dumps(data), encoding='utf-8')
