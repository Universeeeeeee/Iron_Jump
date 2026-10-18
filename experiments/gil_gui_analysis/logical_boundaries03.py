"""Offline logical publication triggers; no GUI, SDK, devices, timing or candidates."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time


ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import numpy as np
from qtpy.QtCore import QCoreApplication,qVersion
from config.walking_config import WalkingConfig
from engine.gait_engine import GaitEngine
from engine.device_quality_session import DeviceQualitySession
from hardware.beam_quality import BeamQualityPolicy
from hardware.sensor_frame import DeviceLayout,SensorSegment,SensorFrame


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def first_difference(a,b,path='$'):
    if type(a)!=type(b):return dict(path=path,actual_type=type(a).__name__,saved_type=type(b).__name__,actual_repr=repr(a)[:160],saved_repr=repr(b)[:160])
    if isinstance(a,dict):
        if set(a)!=set(b):return dict(path=path,actual_keys=sorted(a),saved_keys=sorted(b))
        for k in a:
            d=first_difference(a[k],b[k],path+'.'+str(k))
            if d:return d
    elif isinstance(a,(list,tuple)):
        if len(a)!=len(b):return dict(path=path,actual_length=len(a),saved_length=len(b))
        for i,(x,y) in enumerate(zip(a,b)):
            d=first_difference(x,y,path+'['+str(i)+']')
            if d:return d
    elif a!=b:return dict(path=path,actual_repr=repr(a),saved_repr=repr(b))
    return None


def main(a):
    baseline=read(ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert all(sha(ROOT/n)==h for n,h in baseline.items())
    result=dict(numpy_version=np.__version__,qt_version=qVersion(),errors=[],trigger_events=[],actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False)
    saved_clock=time.perf_counter_ns;saved_profile=sys.getprofile()
    hits=Counter();raw_sample=[None];checked=[None]
    def profile(frame,event,arg):
        if event!='c_call':return
        name=getattr(arg,'__name__','');owner=getattr(arg,'__self__',None)
        if isinstance(owner,np.ndarray) and name in ('all','any'):
            family='ndarray.'+name;size=owner.size
        elif isinstance(owner,np.ufunc) and name=='reduce':
            family=owner.__name__+'.reduce';operand=frame.f_locals.get('a',frame.f_locals.get('obj'));size=operand.size if isinstance(operand,np.ndarray) else None
        else:return
        f=frame;origin=None
        while f is not None:
            try:rel=Path(f.f_code.co_filename).relative_to(ROOT).as_posix()
            except ValueError:rel=''
            if rel.startswith(('engine/','hardware/')):origin=(rel,f.f_code.co_name,f.f_lineno);break
            f=f.f_back
        if origin is None:return
        bucket=(raw_sample[0]-checked[0]-1)//1000
        hits[(bucket,*origin,family,None if size is None else int(size))]+=1
    try:
        m=read(a.capture/'measurement.json');report=read(a.capture/'report.json');meta=report['report_config_snapshot'];device=meta['device']
        with np.load(a.capture/'raw_frames.npz') as archive:data={k:archive[k] for k in archive.files}
        assert digest([[device['stream_id'],[],int(x)] for x in data['dropped_frames_before']])==m['delivered_metadata_sha256'],'Do not assume omitted stream/flags metadata'
        layout=DeviceLayout(tuple(SensorSegment(**s) for s in device['layout']['segments']),tuple(device['layout']['invalid_bit_indices']))
        app=QCoreApplication.instance() or QCoreApplication([])
        cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
        engine=GaitEngine(config=cfg);quality=DeviceQualitySession(cfg,BeamQualityPolicy(),engine);engine.quality=quality
        quality.armed.connect(engine.begin_quality_session);quality.frame_ready.connect(engine.process_quality_frame)
        current=[int(data['received_ns'][0])];time.perf_counter_ns=lambda:current[0];checked[0]=device['checked_sample_index'];sys.setprofile(profile)
        seen=0
        def audit(trigger,phase):
            nonlocal seen
            p=engine.overground.processor
            if p is None:return
            for e in p.event_audit[seen:]:
                if e['action'] in ('publish','retract','sequence_retracted'):
                    result['trigger_events'].append(dict(raw_trigger_sample=trigger,phase=phase,event=dict(e)))
            seen=len(p.event_audit)
        for i,n in enumerate(data['sample_indices']):
            current[0]=int(data['received_ns'][i]);n=int(n);raw_sample[0]=n
            frame=SensorFrame(device['stream_id'],layout,int(data['frame_indices'][i]),n,current[0],data['bits'][i].tobytes(),data['valid_bits'][i].tobytes(),data['wire'][i].tobytes(),int(data['dropped_frames_before'][i]),())
            quality.on_frame(frame);audit(n,'feed')
            if n==device['checked_sample_index']:
                quality.arm_checked((quality._status()['device_key'],True));assert quality.context is not None
        sys.setprofile(saved_profile)
        quality.halt();engine.overground.halt();audit(None,'halt')
        actual=asdict(engine.build_report(report['finish_reason']));actual.pop('export_frames');actual.pop('export_timestamps');audit(None,'report')
        result['report_in_memory_difference']=first_difference(actual,report)
        actual=json.loads(json.dumps(actual))
        result['report_serialized_difference']=first_difference(actual,report)
        assert actual==report,'Full serialized report differs; do not accept a trigger map'
        runtime=quality._runtime;window=hashlib.sha256()
        for bits,changes in runtime._window:window.update(bits.tobytes());window.update(changes.tobytes())
        state=dict(quality=quality.snapshot(),runtime_counts=runtime._counts.tolist(),runtime_transitions=runtime._transitions.tolist(),runtime_healthy=runtime.healthy_samples,runtime_window_sha256=window.hexdigest(),audit=digest(engine.overground.processor.event_audit),timeline=digest(list(engine.overground.processor.timeline)),mirror_events=engine.overground._frame_filter.mirror_guard.events,raw_archive_sha256=hashlib.sha256(b''.join(engine.overground.frames)).hexdigest())
        result['state_in_memory_difference']=first_difference(state,m['state'])
        state=json.loads(json.dumps(state))
        result['state_serialized_difference']=first_difference(state,m['state'])
        assert state==m['state'],'Full serialized quality/runtime/audit/timeline/archive state differs'
        assert all(sha(ROOT/n)==h for n,h in baseline.items())
        result['public_boundary_counts']=[dict(raw_bucket=k[0],file=k[1],function=k[2],line=k[3],boundary=k[4],operand_size=k[5],count=v) for k,v in sorted(hits.items(),key=lambda kv:repr(kv[0]))]
        result['count_limits']='Synchronous logical replay with Python profiling; no elapsed timings, live call-stack identity or wait/release counts. Nested public boundaries are not additive. Does not identify the GIL holder.'
        result.update(full_report_exact=True,full_state_exact=True,numpy_version=np.__version__,qt_version=qVersion(),source_sha256=sha(Path(__file__)),capture_hashes={n:sha(a.capture/n) for n in ('measurement.json','report.json','raw_frames.npz')},publication_map_pass=True)
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        time.perf_counter_ns=saved_clock;sys.setprofile(saved_profile)
        with a.output.open('x') as f:json.dump(result,f,indent=2)
    print({k:v for k,v in result.items() if k not in ('trigger_events','capture_hashes')});return int(bool(result['errors']))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);raise SystemExit(main(p.parse_args()))
