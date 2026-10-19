"""Reuse existing QPC anchors; retain historical media origin separately from current origin."""
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
_native=None
def native_anchor():
    global _native
    if _native is None:
        spec=importlib.util.spec_from_file_location('saved_session_qpc',ROOT/'experiments/gil_gui_calibration/winapi.py')
        _native=importlib.util.module_from_spec(spec);spec.loader.exec_module(_native)
    return _native.anchor()

def validate_anchors(anchors,max_bracket_ns=1000000):
    if len(anchors)!=6:raise ValueError('Parent/measurement/SDK need two anchors each')
    frequencies={a['frequency'] for a in anchors}
    if len(frequencies)!=1 or next(iter(frequencies))<=0:raise ValueError('QPC frequency mismatch')
    for a in anchors:
        before,after=a['perf_before_ns'],a['perf_after_ns'];frequency=a['frequency']
        q0=a['qpc_before']*1000000000//frequency;q1=a['qpc_after']*1000000000//frequency
        if not 0<=after-before<=max_bracket_ns or not before<=q0<=q1<=after:raise ValueError('QPC/perf clock bracket failed')
    return dict(common_qpc_frequency=next(iter(frequencies)),all_six_brackets_pass=True,max_bracket_ns=max(a['perf_after_ns']-a['perf_before_ns'] for a in anchors),disturbance_qualified=False)

class SourceClock:
    def __init__(self,folder):
        self.folder=Path(folder);self.anchor_ns=None;self.original_start_ns=None;self.arm_pause_ns=0;self.history=[]
    def apply(self,value):
        if value['revision']!=len(self.history)+1 or len(self.history)>=2:raise ValueError('Source epoch order changed')
        if not self.history:
            if value['armed'] or value['arm_pause_ns']!=0:raise ValueError('Missing pre-arm source epoch')
            self.original_start_ns=value['original_start_ns']
        else:
            first=self.history[0]
            if not value['armed'] or value['original_start_ns']!=self.original_start_ns or value['arm_pause_ns']<0:raise ValueError('Source identity changed')
            if value['anchor_ns']!=first['anchor_ns']+value['arm_pause_ns']:raise ValueError('Source rebase mismatch')
        self.anchor_ns=value['anchor_ns'];self.arm_pause_ns=value['arm_pause_ns'];self.history.append(dict(value))
