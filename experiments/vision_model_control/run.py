"""Two fresh-process, fixed-call real model controls; not a timing comparison."""
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
digest=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def child(name):
    import cv2
    import numpy as np
    from vision.live_walking import _PreviewAdapter
    plan=json.loads((HERE/'plan01.json').read_text());assert name in plan['cases']
    folder=HERE/'runs'/name;folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir()
    result=dict(calls=[],errors=[],close_confirmed=False,actual_load_disturbance_pass=False);adapter=None
    try:
        assert all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
        assert sha(HERE/'run.py')==plan['run_sha256']
        source=Path(plan['input_root']);assert all(sha(source/n)==v for n,v in plan['input_sha256'].items())
        assert sha(ROOT/'models/pose_landmarker_full.task')==plan['model_sha256']
        # Decode everything before model start; logical order/time cannot depend on runtime speed.
        index={int(x['capture_frame_index']):x for x in csv.DictReader((source/'camera.csv').open())};frames=[]
        with (source/'camera.mjpg').open('rb') as f:
            for frame_id in plan['frame_ids']:
                row=index[frame_id];f.seek(int(row['offset']));encoded=f.read(int(row['length']));frame=cv2.imdecode(np.frombuffer(encoded,dtype=np.uint8),cv2.IMREAD_COLOR);assert frame is not None
                frames.append((frame_id,row,frame,hashlib.sha256(encoded).hexdigest(),time.perf_counter_ns()))
        adapter=_PreviewAdapter(ROOT/'models/pose_landmarker_full.task');adapter.open();result['model_opened']=True
        for position,(frame_id,row,frame,jpeg_sha,decoded_ns) in enumerate(frames):
            logical_ms=1000+position*50;begin=time.perf_counter_ns();pose=adapter.infer_bgr(frame,logical_ms);end=time.perf_counter_ns()
            payload=None if pose is None else asdict(pose)
            result['calls'].append(dict(frame_id=frame_id,media_sample_s=float(row['sample_time']),logical_ms=logical_ms,jpeg_sha256=jpeg_sha,pixels_sha256=hashlib.sha256(frame.tobytes()).hexdigest(),shape=list(frame.shape),decoded_ns=decoded_ns,begin_ns=begin,end_ns=end,has_pose=pose is not None,result_content_sha256=digest(payload)))
        result['complete_calls']=len(result['calls'])==len(plan['frame_ids'])
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        if adapter is not None:
            result['close_begin_ns']=time.perf_counter_ns()
            try:adapter.close();result['close_confirmed']=not adapter.is_open
            except BaseException as exc:result['errors'].append(repr(exc))
            result['close_end_ns']=time.perf_counter_ns()
        with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
    return int(bool(result['errors']) or not result['close_confirmed'] or not result.get('complete_calls'))

if __name__=='__main__':
    if len(sys.argv)>1:raise SystemExit(child(sys.argv[1]))
    plan=json.loads((HERE/'plan01.json').read_text());stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir();status=dict(cases=[],errors=[])
    try:
        for name in plan['cases']:
            with (stage/(name+'.stdout')).open('xb') as out,(stage/(name+'.stderr')).open('xb') as err:
                process=subprocess.Popen([sys.executable,str(HERE/'run.py'),name],stdout=out,stderr=err)
                try:code=process.wait(timeout=180)
                except subprocess.TimeoutExpired:status['unconfirmed_pid']=process.pid;raise
            status['cases'].append(dict(name=name,exit_code=code));assert code==0
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status));raise SystemExit(bool(status['errors']))
