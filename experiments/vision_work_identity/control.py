"""Deterministic operation schedules through original queue/scheduler methods.

No worker/model/device is started. Explicit drains are synthetic scheduling,
not a reconstruction of historical worker wakeups or a performance benchmark.
"""
import hashlib
import json
from pathlib import Path
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
from vision.service import FootVisionService
from vision.event_scheduler import EventWindowScheduler
from vision.foot_reference import VisionConfig


def run(frames,drain_after):
    config=VisionConfig(inference_interval_ms=50,max_frames=20,frame_buffer_ms=1000)
    service=FootVisionService(config,'unused-model',latest_frame_only=True)
    # Test fixture setup only: original submit_frame rejects before start().
    # Opening a real adapter/worker would make this controlled order nondeterministic.
    service._accepting=True;scheduler=EventWindowScheduler(config);ledger=[];inferred=[];pending=None
    def drain():
        nonlocal pending
        values,events=service._take_inputs();assert not events
        for frame,stamp in values:
            ledger.append(dict(stage='dequeue',frame_id=frame,logical_s=stamp,observed_ns=time.perf_counter_ns()))
            cursor=scheduler.inference_cursor_ms;rounded=round(stamp*1000)
            scheduler.add_frame(frame,stamp)
            def infer(value,timestamp_ms):
                inferred.append(dict(frame_id=value,timestamp_ms=timestamp_ms));return None
            scheduler.process_ready(infer,lambda *args:None,now_s=stamp)
            selected=any(x['frame_id']==frame for x in inferred)
            ledger.append(dict(stage='scheduler',frame_id=frame,rounded_ms=rounded,prior_cursor_ms=cursor,selected=selected,
                               reason='inferred' if selected else ('nonincreasing_timestamp' if cursor is not None and rounded<=cursor else 'below_50ms')))
        pending=None
    for index,frame in enumerate(frames):
        if pending is not None:ledger.append(dict(stage='overwritten',frame_id=pending,by_frame_id=frame['frame_id']))
        service.submit_frame(frame['frame_id'],frame['logical_s']);pending=frame['frame_id']
        ledger.append(dict(stage='submit',frame_id=frame['frame_id'],logical_s=frame['logical_s'],observed_ns=time.perf_counter_ns()))
        if index in drain_after:drain()
    drain()
    terminal={f['frame_id']:[] for f in frames}
    for row in ledger:
        if row['stage']=='overwritten':terminal[row['frame_id']].append('overwritten')
        elif row['stage']=='scheduler':terminal[row['frame_id']].append(row['reason'])
    assert all(len(v)==1 for v in terminal.values())
    return dict(inputs=frames,drain_after=drain_after,ledger=ledger,terminal=terminal,inferences=inferred,
                deterministic_work_sha256=hashlib.sha256(json.dumps(inferred,sort_keys=True).encode()).hexdigest(),
                scope='Synthetic queue drain order, original methods, fake inference returning None. Actual observed_ns is separate from logical_s. No real worker/model/SDK or runtime speed inference.')


if __name__=='__main__':
    plan=json.loads((HERE/'plan01.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert all(sha(ROOT/n)==v for n,v in plan['sources'].items())
    output=HERE/'runs/short01';output.mkdir(parents=True,exist_ok=False);(output/'active.lock').mkdir()
    cases={}
    for name,case in plan['cases'].items():cases[name]=run(case['frames'],case['drain_after'])
    result=dict(cases=cases,actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)
    with (output/'result.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({n:dict(inferences=v['inferences'],terminal=v['terminal']) for n,v in cases.items()},indent=2))
