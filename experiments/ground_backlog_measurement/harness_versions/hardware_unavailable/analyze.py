"""Queue emptiness and latency jitter are different observations."""
import json,sys
from pathlib import Path
import numpy as np
from semantics import verify,read,HERE

def stats(values):return {'p50':float(np.median(values)),'p95':float(np.percentile(values,95)),'max':float(max(values))}
def metrics(folder):
    m,s,report,received,active=verify(folder)
    points=m['queue_common'];data=s['data'];indices=data['sample_indices']
    for r in points+m['queue_samples']:
        assert r[7]>=r[3]>=0 and r[8]==r[7]-r[3]
        assert (r[9]=='empty')==(r[3]==r[7]==0)
        assert (r[4] is None)==(r[3]==0)
    lookup=dict(zip(indices.tolist(),received.tolist()))
    lat=[(m['paints'][str(e['contact_id'])]-lookup[e['touch_sample']])/1e6 for e in active]
    out={'name':folder.name,'mode':m['mode'],'load':m['load'],'variant':m['variant'],'probe':m['probe'],'footprint_p95_ms':float(np.percentile(lat,95)),'footprint_max_ms':max(lat),'phases':[],'semantic_exact':True,'native':m['native'],'camera':m['camera'],'pose_draws':m['pose_draws'],'sdk':m['sdk']}
    for group in s['groups']:
        rows=[r for r in points if group['start']<=r[1]<group['end']]
        assert len(rows)>2
        ages=[(r[0]-r[2])/1e6 for r in rows]
        q=[r[3] for r in rows];pending_age=[0 if r[4] is None else (r[0]-r[4])/1e6 for r in rows]
        times=np.array([r[0] for r in rows],dtype=np.float64)/1e9;delta=np.diff(times)
        auc=float(np.sum((np.array(q[:-1])+q[1:])*.5*delta))
        span=0.;begin=None;previous=None
        for r in rows:
            on=r[3]>=100 and r[4] is not None and r[0]-r[4]>=100000000
            if on:
                if begin is None or previous is None or r[0]-previous>250000000:begin=r[0]
                span=max(span,(r[0]-begin)/1e9);previous=r[0]
            else:begin=previous=None
        source_rows=[v for v in m['arrivals'] if group['start']<=v[2]<group['end']]
        source_fps=(source_rows[-1][2]-source_rows[0][2])*1e9/(source_rows[-1][0]-source_rows[0][0])
        fps=(rows[-1][1]-rows[0][1])*1e9/(rows[-1][0]-rows[0][0])
        out['phases'].append({**group,'consumer_fps':fps,'actual_arrival_fps':source_fps,'deficit_to_1000_fps':max(0,1000-fps),'deficit_to_actual_arrival_fps':max(0,source_fps-fps),'completion_age_ms':stats(ages),'completion_age_slope_ms_per_device_second':float(np.polyfit([(r[1]-rows[0][1])/1000 for r in rows],ages,1)[0]),'queue_depth':stats(q),'oldest_pending_age_ms':stats(pending_age),'oldest_pending_age_nonempty_ms':stats([v for r,v in zip(rows,pending_age) if r[3]]) if any(q) else None,'pending_auc_frame_seconds':auc,'heavy_queue_observed_span_s':span,'empty_witnesses':sum(r[9]=='empty' for r in rows),'common_max_gap_ms':float(max(delta)*1000)})
    bits=data['bits'].copy();bits[:,s['bad']]=0
    last=int(indices[np.flatnonzero(np.any(bits,axis=1)&(indices>s['checked']))[-1]])
    due={n:t for _,t,n in m['arrivals']};empty=next((r for r in points if r[1]>=last and r[9]=='empty' and r[0]>=due[last]),None)
    out['last_usable_contact_sample']=last
    out['first_observed_empty_s']=None if empty is None else (empty[0]-due[last])/1e9
    tail=[r for r in points if r[1]>last]
    out['completion_jitter_after_contact_ms']=stats([(r[0]-r[2])/1e6 for r in tail])
    out['empty_witness_high_completion_age_count']=sum(r[9]=='empty' and r[0]-r[2]>25000000 for r in tail)
    out['reader_lag_ms']=stats([(a-b)/1e6 for a,b,n in m['arrivals'] if n>s['checked']])
    dense=next(r for r in out['phases'] if r['phase']=='dense')
    out['representative_consumer_shortage']=(dense['actual_arrival_fps']>=990 and dense['consumer_fps']<970 and dense['heavy_queue_observed_span_s']>=1 and dense['completion_age_slope_ms_per_device_second']>10)
    return out

if __name__=='__main__':
    result=metrics(Path(sys.argv[1]));print(json.dumps(result,indent=2))
