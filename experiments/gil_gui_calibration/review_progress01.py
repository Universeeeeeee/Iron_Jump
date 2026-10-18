"""Recompute exploratory queue, publication and work-alignment evidence offline."""
import argparse
import json
from pathlib import Path
import numpy as np
from review_aa01 import counters,read,sha


def queue_metrics(m,start,end):
    points=m['queue_common'];assert all(b[0]>=a[0] and b[1]>=a[1] for a,b in zip(points,points[1:]))
    assert all(r[7]>=r[3]>=0 and r[8]==r[7]-r[3] for r in points)
    rows=[r for r in points if start<=r[1]<end];arr=[r for r in m['arrivals'] if start<=r[2]<end];assert len(rows)>2 and len(arr)>2
    span=0;begin=previous=None
    for r in rows:
        if r[3]>=100 and r[4] is not None and r[0]-r[4]>=100000000:
            if begin is None or previous is None or r[0]-previous>250000000:begin=r[0]
            span=max(span,(r[0]-begin)/1e9);previous=r[0]
        else:begin=previous=None
    return dict(dense_raw_range=[start,end],common_points=len(rows),actual_arrival_fps=(arr[-1][2]-arr[0][2])*1e9/(arr[-1][0]-arr[0][0]),consumer_fps=(rows[-1][1]-rows[0][1])*1e9/(rows[-1][0]-rows[0][0]),max_pending=max(r[3] for r in rows),max_oldest_pending_ms=max((r[0]-r[4])/1e6 if r[4] is not None else 0 for r in rows),heavy_observed_span_s=span,whole_case_max_pending=max(r[3] for r in points))


def publications(m,report):
    received={n:host for host,due,n in m['arrivals']};active=[e for e in report['walking_summary']['event_publications'] if e['active']]
    events=[dict(contact_id=e['contact_id'],touch_sample=e['touch_sample'],receipt_to_first_paint_ms=(m['paints'][str(e['contact_id'])]-received[e['touch_sample']])/1e6) for e in active]
    assert events and all(e['receipt_to_first_paint_ms']>=0 for e in events)
    return dict(events=events,p95_ms=float(np.percentile([e['receipt_to_first_paint_ms'] for e in events],95)),max_ms=max(e['receipt_to_first_paint_ms'] for e in events),limits='Actual received-input to first saved confirmed paint, includes normal publication/processing latency. Not physical step-to-screen or GUI-only time.')


def work_alignment(record,m,clock):
    f=clock['qpc_frequency'];lo=clock['host_ns_offset_lower'];hi=clock['host_ns_offset_upper'];out={}
    for phase in ('before','after'):
        r=next(t for t in record[phase] if t['role']=='consumer');left=r['start']['qpc_before']*10**9//f+lo;right=(r['end']['qpc_after']*10**9+f-1)//f+hi
        lower=max(row[1] for row in m['queue_common'] if row[0]<=left);upper=min(row[1] for row in m['queue_common'] if row[0]>=right)
        out[phase]=dict(host_bracket_ns=[left,right],completed_batch_sample_bounds=[lower,upper],possible_processed_sample_bounds=[lower,upper+20])
    return out


def main(a):
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items())
    base=a.raw/'experiments/gil_gui_calibration';phase=next(g for g in read(base/'phases.json')['walk'] if g['phase']=='dense');status=read(base/'runs/off_aa01/result01.json')
    result=dict(scope='Exploratory existing queue/paint/counter evidence only. No new gate, sampling, physical ground truth, scheduling labels, function shares or field qualification.',manifest_sha256=sha(a.raw/'manifest.json'),reviewer_sha256=sha(Path(__file__)),cases={},actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False)
    for name in status['cases']:
        folder=base/'runs/off_aa01'/name;m=read(folder/'capture/measurement.json');record=read(folder/'record01.json');report=read(folder/'capture/report.json');clock=counters(record)['clock']
        result['cases'][name]=dict(queue=queue_metrics(m,phase['start'],phase['end']),publication=publications(m,report),counter_work=work_alignment(record,m,clock))
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print({k:dict(max_pending=v['queue']['whole_case_max_pending'],paint_max_ms=v['publication']['max_ms']) for k,v in result['cases'].items()})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
