"""Two workload-phase context reads per role using the existing read-only reader."""
from functools import wraps
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments/gui_qos_candidate'))
from runtime_context import snapshot

class Phases:
    def __init__(self,rows,checkpoints,clock=lambda:None,reader=snapshot):
        self.rows=rows;self.checkpoints=checkpoints;self.clock=clock;self.reader=reader;self.seen=set()
    def observe(self,role,completed_sample=None):
        clock=self.clock()
        for p in self.checkpoints:
            key=(role,p['sample'])
            if key in self.seen:continue
            if role=='consumer':ready=completed_sample is not None and completed_sample>=p['sample']
            else:ready=clock is not None and len(clock.history)==2 and time.perf_counter_ns()>=clock.anchor_ns+p['offset_ns']
            if not ready:continue
            self.seen.add(key)
            try:
                value=self.reader(role,p['sample']);value['checkpoint']=p['phase']
                value['after_original_call']=True;value['completed_sample']=completed_sample
                value['source_due_ns']=None if role=='consumer' else clock.anchor_ns+p['offset_ns']
                self.rows.append(value)
            except BaseException as exc:self.rows.append(dict(role=role,ordinal=p['sample'],error=repr(exc)))
    def wrap(self,original,role):
        @wraps(original)
        def call(*args,**kwargs):
            value=original(*args,**kwargs)
            if role=='consumer':
                items=args[1];last=None if not items else items[-1][1].sample_index
                self.observe(role,last)
            else:self.observe(role)
            return value
        return call
    def install(self,roles):
        from ui.session_controller import _GroundFrameInbox
        from vision.live_walking import _PreviewAdapter
        from ui.annotation_canvas import AnnotationCanvas
        targets=dict(consumer=(_GroundFrameInbox,'_consume'),model=(_PreviewAdapter,'infer_bgr'),gui=(AnnotationCanvas,'_draw_live_pose'))
        originals=[]
        for role in roles:
            cls,name=targets[role];original=getattr(cls,name);originals.append((cls,name,original));setattr(cls,name,self.wrap(original,role))
        return originals

def restore(originals):
    for cls,name,original in reversed(originals):setattr(cls,name,original)

def check(rows,backend):
    expected={(role,n) for role in ('gui','model','consumer') for n in (59904,65904)}
    assert len(rows)==6 and {(r['role'],r['ordinal']) for r in rows}==expected
    assert all('error' not in r and r['after_original_call'] and r['session_id']!=0 and r['priority_class']==16384 and 0<=r['end_ns']-r['begin_ns']<=50000000 and r['process']['success'] and r['thread']['success'] for r in rows)
    assert all(r['completed_sample'] is not None and r['ordinal']<=r['completed_sample']<=r['ordinal']+19 if r['role']=='consumer' else r['source_due_ns'] is not None and r['begin_ns']>=r['source_due_ns'] for r in rows)
    by={role:{r['pid'] for r in rows if r['role']==role} for role in ('gui','model','consumer')}
    assert all(len(v)==1 for v in by.values()) and by['gui']==by['model']
    assert (by['consumer']==by['gui'])==(backend=='original')
    tids={role:{(r['pid'],r['tid']) for r in rows if r['role']==role} for role in by}
    assert all(len(v)==1 for v in tids.values()) and len(set().union(*tids.values()))==3
    gui_pid=next(iter(by['gui']))
    return dict(context_reads_pass=True,role_pids={k:next(iter(v)) for k,v in by.items()},
        foreground_self={f"{r['role']}/{r['ordinal']}":r['foreground_pid']==r['pid'] for r in rows},
        foreground_gui={f"{r['role']}/{r['ordinal']}":r['foreground_pid']==gui_pid for r in rows},
        policy={f"{r['role']}/{r['ordinal']}":dict(process=r['process'],thread=r['thread']) for r in rows},
        scope='Two phase checkpoints after original calls; not continuous scheduler coverage or observer-disturbance qualification.')
