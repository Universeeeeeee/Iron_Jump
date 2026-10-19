"""Count/hash entry arguments in original full-chain oracle; never benchmark hooks."""
from collections import Counter
from dataclasses import fields,is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def canonical(value):
    if isinstance(value,Enum):return dict(enum=type(value).__qualname__,value=canonical(value.value))
    if value is None or isinstance(value,(bool,int,float,str)):return value
    if isinstance(value,bytes):return dict(bytes_hex=value.hex())
    if is_dataclass(value):return dict(dataclass=type(value).__qualname__,fields={f.name:canonical(getattr(value,f.name)) for f in fields(value)})
    if isinstance(value,dict):return dict(mapping=sorted([(canonical(k),canonical(v)) for k,v in value.items()],key=lambda x:json.dumps(x[0],sort_keys=True)))
    if isinstance(value,(tuple,list)):return dict(sequence_type=type(value).__name__,items=[canonical(x) for x in value])
    raise TypeError('Unqualified argument type: '+type(value).__qualname__)

def child(name):
    plan=json.loads((HERE/'plan01.json').read_text());assert name in plan['cases'];folder=HERE/'runs'/name;folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir()
    result=dict(errors=[],stages={},actual_load_disturbance_pass=False);restore=[]
    try:
        root=Path(plan['replay_root']);sys.path.insert(0,str(root/'experiments/walk_compute_offline_diagnosis'));import replay
        assert sha(HERE/'run.py')==plan['run_sha256']
        baseline=json.loads((root/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
        assert all(sha(root/n)==v for n,v in baseline.items())
        assert sha(Path(replay.__file__))==plan['replay_sha256']
        assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
        app=replay.QCoreApplication.instance() or replay.QCoreApplication([]);trial=replay.Trial(Path(plan['input_root']));depth=Counter();slots={}
        for cls,names,group in ((replay.GroundStabilityFilter,('feed','reset','flush'),'filter'),(replay.WalkingProcessor,('process','_record_visual','summary','build_report','break_continuity'),'processor')):
            for method in names:
                original=getattr(cls,method);restore.append((cls,method,original))
                def wrapped(obj,*args,_original=original,_method=method,_group=group,**kwargs):
                    top=depth[_group]==0;depth[_group]+=1
                    try:
                        if top:
                            raw=trial.outer;block='preflight' if raw<trial.start else str((raw-trial.start)//1000)
                            key=(_group,block);slot=slots.setdefault(key,dict(counts=Counter(),digest=hashlib.sha256()))
                            payload=json.dumps(dict(raw=raw,method=_method,args=canonical(args),kwargs=canonical(kwargs)),sort_keys=True,separators=(',',':'),allow_nan=False).encode()
                            slot['digest'].update(len(payload).to_bytes(8,'little'));slot['digest'].update(payload);slot['counts'][_method]+=1
                        return _original(obj,*args,**kwargs)
                    finally:depth[_group]-=1
                setattr(cls,method,wrapped)
        trial.oracle()
        assert all(sha(root/n)==v for n,v in baseline.items())
        assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
        for (group,block),slot in slots.items():result['stages'].setdefault(group,{})[block]=dict(counts=dict(slot['counts']),ordered_entry_arguments_sha256=slot['digest'].hexdigest())
        result.update(complete=True,full_original_oracle_exact=True,report_sha256=trial.report_hash,final_state=trial.final_state,formal_start=trial.start,formal_end=trial.end,
                      scope='Whole original chain with entry argument hashing before original call. Only listed top-level filter/processor boundaries; not internal work counts, NumPy operators, allocations or CPU cost. Heavy diagnostic overhead unqualified.')
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        for cls,method,original in restore:setattr(cls,method,original)
        with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
    return int(bool(result['errors']))

if __name__=='__main__':
    if len(sys.argv)>1:raise SystemExit(child(sys.argv[1]))
    plan=json.loads((HERE/'plan01.json').read_text());stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir();status=dict(cases=[],errors=[])
    try:
        for name in plan['cases']:
            with (stage/(name+'.stdout')).open('xb') as out,(stage/(name+'.stderr')).open('xb') as err:
                p=subprocess.Popen([sys.executable,str(HERE/'run.py'),name],stdout=out,stderr=err)
                try:code=p.wait(timeout=240)
                except subprocess.TimeoutExpired:status['unconfirmed_pid']=p.pid;raise
            status['cases'].append(dict(name=name,exit_code=code));assert code==0
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status));raise SystemExit(bool(status['errors']))
