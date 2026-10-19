"""Exactly32 readonly native-counter reads; no model, replay or compute probe."""
import json
from pathlib import Path
import statistics
import time
from ledger import NativeReader,validate_read
HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    begin=time.perf_counter_ns();reader=NativeReader();initialization=time.perf_counter_ns()-begin;rows=[];errors=[]
    for i in range(32):
        try:
            v=reader();rows.append(v);validate_read(v)
        except Exception as exc:errors.append(dict(ordinal=i,error=repr(exc)))
    identities={(r['pid'],r['tid'],r['process']['creation_100ns'],r['thread']['creation_100ns']) for r in rows}
    if len(identities)!=1:errors.append(dict(error='Native identity changed'))
    for a,b in zip(rows,rows[1:]):
        if any(a[role][k]>b[role][k] for role in ('process','thread') for k in ('kernel_100ns','user_100ns','cycles')):errors.append(dict(error='Native counter regressed'))
    result=dict(passed=not errors and len(rows)==32,errors=errors,rows=rows,reader_initialization_ns=initialization,
        read_ns_median=statistics.median(r['end_ns']-r['begin_ns'] for r in rows) if rows else None,read_ns_max=max((r['end_ns']-r['begin_ns'] for r in rows),default=None),
        active_compute_probe=False,model_orhardware_started=False,actual_load_disturbance_pass=False,scope='Unloaded readonlyAPI/ABI/cost check only; no actualGUI observer certification orhardwarefrequency measurement.')
    with (HERE/'native_check01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}));raise SystemExit(not result['passed'])
