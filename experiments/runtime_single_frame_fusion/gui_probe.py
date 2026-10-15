"""Frozen low-volume GUI observation, using a materialized A/B/C baseline."""
import functools
import hashlib
import importlib
import json
from pathlib import Path
import platform
import runpy
import sys
import time
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(HERE)]
from fused_runtime import warmup
from install_variant import install
j = sys.argv.index('--variant')
variant = sys.argv[j+1]
del sys.argv[j:j+2]
out = Path(sys.argv[sys.argv.index('--output')+1])
preheat_started = time.perf_counter()
compilation = warmup()
preheat_seconds = time.perf_counter() - preheat_started
install(variant)
module = importlib.import_module('engine.modes.overground_running_processor')
processor_file=module.OvergroundRunningProcessor.process.__code__.co_filename
event_stages={}
_sync=module.OvergroundRunningProcessor._sync_touch_publications
def staged_sync(self):
    now=time.perf_counter_ns()
    for contact in self.contacts:
        if contact.confirmed:
            event_stages.setdefault(contact.id,{}).setdefault('confirmation_observed_host_ns',now)
    result=_sync(self)
    now=time.perf_counter_ns()
    for cid,event in self._touch_events.items():
        if event['active']:
            event_stages.setdefault(cid,{}).setdefault('publication_observed_host_ns',now)
    return result
module.OvergroundRunningProcessor._sync_touch_publications=staged_sync

spans=[];queues=[];controllers=[];started=time.perf_counter_ns();inference=[]

def wrap(cls,name,role):
    original=getattr(cls,name)
    @functools.wraps(original)
    def measured(*args,**kwargs):
        a=time.perf_counter_ns();c=time.thread_time_ns()
        try:return original(*args,**kwargs)
        finally:spans.append((role,a,time.perf_counter_ns(),time.thread_time_ns()-c))
    setattr(cls,name,measured)

from engine.device_quality_session import DeviceQualitySession
import engine.device_quality_session as delivered_quality
assert delivered_quality.RuntimeBeamEvidence.__name__ == ('RuntimeBeamEvidence' if variant == 'A' else 'FusedRuntime')
from engine.overground_session import OvergroundSession
import engine.overground_session as actual_session
assert actual_session.GroundStabilityFilter.__module__ == 'hardware.beam_filter'
# Finite-file EOF is not a hardware silence fault: drain all accepted raw frames.
for cls in (DeviceQualitySession,OvergroundSession):
    original_poll=cls.poll
    def finite_poll(self,_poll=original_poll):
        worker=controllers[-1]._worker if controllers else None
        if worker is not None and getattr(worker,'exhausted_ns',None) is not None:return
        return _poll(self)
    cls.poll=finite_poll
from ui.session_controller import SessionController,_GroundFrameInbox
original_init=SessionController.__init__
def init(self,*a,**kw):
    original_init(self,*a,**kw);controllers.append(self)
SessionController.__init__=init
original_consume=_GroundFrameInbox._consume
def consume(self,items):
    a=time.perf_counter_ns();cpu=time.thread_time_ns()
    original_consume(self,items)
    frames=[v for issue,v in items if not issue]
    if frames:
        self.probe_last_sample=frames[-1].sample_index
        self.probe_count=getattr(self,'probe_count',0)+len(frames)
        queues.append((a,time.perf_counter_ns(),len(frames),self.probe_last_sample,
                       (a-frames[0].received_monotonic_ns)/1e6,time.thread_time_ns()-cpu))
_GroundFrameInbox._consume=consume
wrap(SessionController,'stop','stop')
from ui.embedded_camera_panel import EmbeddedCameraPanel
from ui.annotation_canvas import AnnotationCanvas
from ui.ground_track import GroundChannelWidget
from ui.views.execution_view import ExecutionView
wrap(EmbeddedCameraPanel,'_render_frame','preview_prepare')
wrap(AnnotationCanvas,'paintEvent','preview_paint')
wrap(GroundChannelWidget,'paintEvent','track_paint')
wrap(ExecutionView,'on_footprint_visual_frame','visual_slot')
from vision.live_walking import _PreviewAdapter
wrap(_PreviewAdapter,'infer_bgr','inference')

from qtpy.QtCore import QTimer
import qtpy.QtWidgets as widgets
BaseApp=widgets.QApplication
samples=[];ticks=[]
class App(BaseApp):
    def __init__(self,*a):
        super().__init__(*a)
        self.tick_timer=QTimer(self);self.tick_timer.setInterval(10)
        self.tick_timer.timeout.connect(lambda:ticks.append(time.perf_counter_ns()));self.tick_timer.start()
        self.queue_timer=QTimer(self);self.queue_timer.setInterval(50)
        self.queue_timer.timeout.connect(self.sample);self.queue_timer.start()
    def sample(self):
        if not controllers:return
        controller=controllers[-1];inbox=controller._frame_inbox
        if inbox is None:return
        now=time.perf_counter_ns()
        with inbox._lock:
            pending=len(inbox._pending)
            first=next((v.received_monotonic_ns for issue,v in inbox._pending if not issue),None)
        panel=next((w for w in self.allWidgets() if isinstance(w,EmbeddedCameraPanel)),None)
        samples.append((now,pending,(now-first)/1e6 if first else 0,getattr(inbox,'probe_count',0),
                        bool(panel and panel._overlay_visible),panel._vision._service_status if panel and panel._vision else None))
widgets.QApplication=App
try:
    runpy.run_path(str(HERE/'fixed_replay.py'), run_name='__main__')
finally:
    if out.exists():
        import numpy, numba, qtpy
        names = ['fused_runtime.py', 'install_variant.py', 'gui_probe.py', 'fixed_replay.py', 'fixed_geometry_cache.py']
        data = {'runtime': variant, 'event_stages': event_stages, 'spans': spans, 'queues': queues,
                'samples': samples, 'ticks': ticks, 'started_ns': started,
                'preheat_seconds': preheat_seconds, 'compilation': compilation,
                'environment': {'python': sys.version, 'platform': platform.platform(),
                                'numpy': numpy.__version__, 'numba': numba.__version__, 'qt': qtpy.QT_VERSION},
                'executed_quality_file': delivered_quality.DeviceQualitySession.on_frame.__code__.co_filename,
                'artifact_hashes': {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in names},
                'source_hashes': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                                  json.loads((HERE/'baseline_manifest.json').read_text())['base_files']}}
        (out/'probe.json').write_text(json.dumps(data), encoding='utf-8')
