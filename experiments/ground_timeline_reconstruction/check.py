"""Independent chronological sweep and old-evidence integrity checks."""
import csv,hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
SOURCE=HERE.parent/'ground_backlog_measurement'
sys.path.insert(0,str(HERE))
from reconstruct import TRIALS

def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def counts(due,prepared,t,E,C):
    S=sum(v<=t for v in due);A=sum(v<=t for v in prepared)
    return S-A,A-E,E-C
assert counts([0,1,2],[0,10,11],5,1,1)==(2,0,0)
assert counts([0,1,2],[0,1,2],5,3,1)==(0,0,2)
assert counts([0,1,2],[0,1,10],5,2,1)==(1,0,1)
checks=[]
for name,_ in TRIALS:
    m=json.loads((SOURCE/'runs'/name/'measurement.json').read_text())
    q=sorted(m['queue_common']+m['queue_samples'],key=lambda r:r[0]);a=m['arrivals'];n0=a[0][2]
    rows=list(csv.DictReader((HERE/'snapshots'/(name+'.csv')).open()));assert len(q)==len(rows)
    S=A=0
    for r,out in zip(q,rows):
        while S<len(a) and a[S][1]<=r[0]:S+=1
        while A<len(a) and a[A][0]<=r[0]:A+=1
        E=r[5]-n0+1;C=r[1]-n0+1
        assert [int(out[k]) for k in ('S_planned','A_prepared','E_enqueued','C_batch_ack')]==[S,A,E,C]
        assert [int(out[k]) for k in ('upstream_not_prepared','prepared_not_enqueued','enqueued_not_batch_ack')]==[S-A,A-E,E-C]
        assert int(out['pending_exact'])==r[3]
    frame=list(csv.DictReader((HERE/'frames'/(name+'.csv')).open()));assert len(frame)==len(a)
    for r in q:
        E=r[5]-n0+1
        if E<len(a):assert int(frame[E]['enqueue_upper_ns'])>=r[0]
        if E:assert int(frame[E-1]['enqueue_upper_ns'])<=r[0]
    cam=list(csv.DictReader((SOURCE/'runs'/name/'native_camera.csv').open()));offset=0
    for i,r in enumerate(cam,1):
        assert int(r['record_frame_index'])==i and int(r['offset'])==offset;offset+=int(r['length'])
    assert offset==m['native']['writer']['bytes_written'] and len(cam)==m['native']['writer']['frames_written']
    assert h(SOURCE/'runs'/name/'native_camera.csv')==m['native']['record_files']['native_camera.csv']['sha256']
    checks.append({'name':name,'all_snapshots_independently_counted':len(rows),'all_frame_enqueue_bounds_checked':len(frame),'native_CSV_offsets_and_bytes_exact':True})
old=json.loads((SOURCE/'final_evidence_manifest.json').read_text())
for group in ('local_metadata','logs'):
    for rel,v in old[group].items():assert h(SOURCE/rel)==v['sha256'],rel
base=json.loads((ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
for rel,value in base.items():assert h(ROOT/rel)==value,rel
for rel,v in json.loads((HERE/'input_manifest.json').read_text()).items():assert h(SOURCE/rel)==v['sha256'],rel
result={'synthetic_upstream_only_downstream_only_and_mixed_cases_pass':True,'trials':checks,'old_evidence_files_unchanged':sum(len(old[k]) for k in ('local_metadata','logs')),'baseline_files_unchanged':len(base),'new_probes_or_replays':0,'AA_runs':0,'AB_runs':0}
(HERE/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
