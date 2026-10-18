"""Offline interval bounds from original queue witnesses and verified logical triggers."""
import argparse
from bisect import bisect_left,bisect_right
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'))
import numpy as np
from review_aa01 import read,sha,counters


def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def completed_at(rows,stamp,final_sample):
    times=[r[0] for r in rows];left=bisect_left(times,stamp);right=bisect_right(times,stamp)
    if left<right:return [rows[left][1],rows[right-1][1]]
    if left==0:return None
    if left==len(rows):return [final_sample,final_sample] if rows[-1][1]==final_sample else None
    return [rows[left-1][1],rows[left][1]]


def completion_bracket(rows,sample):
    values=[r[1] for r in rows];i=bisect_left(values,sample)
    if i==0 or i==len(rows):raise ValueError('No two-sided completion witness')
    return [rows[i-1][0],rows[i][0]]


def validate_queue(m,received):
    rows=m['queue_common'];assert all(a[0]<=b[0] and a[1]<=b[1] for a,b in zip(rows,rows[1:]))
    allrows=sorted(rows+m['queue_samples'],key=lambda r:r[0]);checked=0;max_inflight=0
    for r in allrows:
        assert r[7]==r[5]-r[1] and r[8]==r[7]-r[3] and r[7]>=r[3]>=0
        if r[1] in received:assert r[2]==received[r[1]]
        else:assert r[1]==min(received)-1 and r[2]==0
        assert r[6]==received[r[5]]
        if r[3]:
            oldest=r[5]-r[3]+1;assert received[oldest]==r[4] and r[0]>=r[4];checked+=1
        else:assert r[4] is None
        if r[0]>=m['armed_ns']:
            max_inflight=max(max_inflight,r[8]);assert r[8]<=20,'Cannot use normal20-frame bound'
    assert all(a[5]<=b[5] for a,b in zip(allrows,allrows[1:])), 'Latest arrival regressed'
    assert all(r[12]==0 and r[9]!='batch' for r in rows),'Common witness was not between batches'
    return dict(oldest_pending_receipts_independently_matched=checked,max_post_arm_inflight=max_inflight,queue_common_monotone=True)


def queue_cursor_brackets(m,sample):
    rows=sorted(m['queue_common']+m['queue_samples'],key=lambda r:r[0])
    enqueued=[r[5] for r in rows];popped=[r[5]-r[3] for r in rows]
    assert all(x<=y for x,y in zip(enqueued,enqueued[1:]))
    assert all(x<=y for x,y in zip(popped,popped[1:])), 'FIFO dequeue prefix regressed'
    def bound(values):
        i=bisect_left(values,sample)
        if i==0 or i==len(rows):raise ValueError('Missing enqueue/dequeue bracket')
        return [rows[i-1][0],rows[i][0]]
    return dict(enqueued=bound(enqueued),popped=bound(popped))


def event_bounds(m,report,received,trigger_map):
    out=[]
    for e in report['walking_summary']['event_publications']:
        if not e['active']:continue
        key=e['event_id'];trigger=trigger_map[key];raw=trigger['raw_trigger_sample']
        assert trigger['phase']=='feed' and trigger['event']['published_sample']==e['published_sample']
        assert trigger['event']['touch_sample']==e['touch_sample'] and e['revision']==1
        lower,upper=completion_bracket(m['queue_common'],raw);lower=max(lower,received[raw])
        paint=m['paints'][str(e['contact_id'])];assert lower<=paint,'Paint predates proven publication lower bound'
        cursors=queue_cursor_brackets(m,raw);enq=[max(received[raw],cursors['enqueued'][0]),cursors['enqueued'][1]];pop=cursors['popped']
        assert enq[0]<=enq[1] and pop[0]<=upper and enq[0]<=pop[1]
        residence=[max(0,pop[0]-enq[1])/1e6,(pop[1]-enq[0])/1e6]
        processing=[max(0,lower-pop[1])/1e6,(upper-pop[0])/1e6]
        out.append(dict(contact_id=e['contact_id'],touch_sample=e['touch_sample'],published_sample=e['published_sample'],raw_release_trigger=raw,
            source_confirmation_sample_span=raw-e['touch_sample'],source_confirmation_time_ms=(received[raw]-received[e['touch_sample']])/1e6,
            enqueue_host_bounds_ns=enq,dequeue_host_bounds_ns=pop,queue_residence_bounds_ms=residence,dequeue_to_publication_bounds_ms=processing,
            publication_host_bounds_ns=[lower,upper],source_trigger_to_publication_ms=[(lower-received[raw])/1e6,(upper-received[raw])/1e6],
            publication_to_paint_raw_bounds_ms=[(paint-upper)/1e6,(paint-lower)/1e6],
            publication_to_paint_nonnegative_bounds_ms=[max(0,(paint-upper)/1e6),(paint-lower)/1e6],
            source_touch_to_paint_ms=(paint-received[e['touch_sample']])/1e6))
    return out


def host_bins(m,last_sample):
    end=math.ceil((m['queue_common'][-1][0]-m['armed_ns'])/1e9);out=[]
    for i in range(end):
        start=m['armed_ns']+i*10**9;finish=start+10**9
        a=completed_at(m['queue_common'],start,last_sample);b=completed_at(m['queue_common'],finish,last_sample)
        rows=[r for r in m['queue_common'] if start<=r[0]<finish];arr=[r for r in m['arrivals'] if start<=r[0]<finish]
        out.append(dict(host_second=i,source_generated_frames=len(arr),batch_completed_frame_count_bounds=None if a is None or b is None else [max(0,b[0]-a[1]),max(0,b[1]-a[0])],
            observed_pending_max=max((r[3] for r in rows),default=None),observed_oldest_pending_ms_max=max(((r[0]-r[4])/1e6 if r[4] is not None else 0 for r in rows),default=None)))
    return out


def analyze_case(folder,oracle,reference):
    m=read(folder/'capture/measurement.json');report=read(folder/'capture/report.json');record=read(folder/'record01.json');native=counters(record)
    with np.load(folder/'capture/raw_frames.npz') as data:raw={k:data[k] for k in data.files}
    for k in reference:
        if k!='usable_contact':assert np.array_equal(raw[k],reference[k]),'Logical input differs: '+k
    assert digest([[report['report_config_snapshot']['device']['stream_id'],[],int(x)] for x in raw['dropped_frames_before']])==m['delivered_metadata_sha256']
    assert m['state']['audit']==oracle['audit_sha256'] and m['state']['timeline']==oracle['timeline_sha256']
    received={int(n):int(t) for n,t in zip(raw['sample_indices'],raw['received_ns'])}
    assert list(received)==list(range(int(raw['sample_indices'][0]),int(raw['sample_indices'][-1])+1))
    assert all(received[n]==t for t,due,n in m['arrivals'])
    validation=validate_queue(m,received);events=event_bounds(m,report,received,oracle['triggers'])
    peak=max(m['queue_common'],key=lambda r:r[3]);first_contact=int(raw['sample_indices'][np.flatnonzero(reference['usable_contact'])[0]])
    second_bins=host_bins(m,int(raw['sample_indices'][-1]))
    return dict(queue_validation=validation,native=native,events=events,host_bins=second_bins,
        first_raw_contact_source_host_s=(received[first_contact]-m['armed_ns'])/1e9,
        first_reported_touch_source_host_s=min((received[e['touch_sample']]-m['armed_ns'])/1e9 for e in events),
        peak=dict(host_s=(peak[0]-m['armed_ns'])/1e9,pending=peak[3],oldest_pending_ms=0 if peak[4] is None else (peak[0]-peak[4])/1e6,completed_sample=peak[1],latest_enqueued_sample=peak[5]),
        maximum_downstream_upper_ms=max(e['publication_to_paint_nonnegative_bounds_ms'][1] for e in events),
        max_total_event=max(events,key=lambda e:e['source_touch_to_paint_ms']))


def main(a):
    mapping=read(a.oracle);assert mapping.get('publication_map_pass') and not mapping['errors']
    first=a.prior/'experiments/gil_gui_calibration/runs/off_aa01/pair01_a/capture';m=read(first/'measurement.json')
    with np.load(first/'raw_frames.npz') as data:reference={k:data[k] for k in data.files if k!='received_ns'}
    bits=reference['bits'].astype(bool)&reference['valid_bits'].astype(bool);bad=read(first/'report.json')['report_config_snapshot']['device']['bad_indices'];bits[:,bad]=False
    usable=np.any(bits,axis=1);usable[reference['sample_indices']<=read(first/'report.json')['report_config_snapshot']['device']['checked_sample_index']]=False
    proof=dict(triggers={e['event']['event_id']:e for e in mapping['trigger_events'] if e['event']['action']=='publish'},audit_sha256=m['state']['audit'],timeline_sha256=m['state']['timeline'])
    result=dict(cases={},source_sha256=sha(Path(__file__)),oracle_sha256=sha(a.oracle),manifests={},actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False)
    for label,root,stage in [('prior',a.prior,'off_aa01'),('repeat',a.repeat,'restart_repeat01')]:
        manifest=read(root/'manifest.json');assert all(sha(root/n)==h for n,h in manifest.items());result['manifests'][label]=sha(root/'manifest.json')
        for folder in sorted((root/'experiments/gil_gui_calibration/runs'/stage).glob('pair*')):
            # Only a derived occupancy vector is extra; it is not part of the raw equality checks.
            item=analyze_case(folder,proof,reference|{'usable_contact':usable})
            result['cases'][label+'/'+folder.name]=item
    result['limits']=['No exact host publication timestamp was saved. Brackets use between-batch common witnesses and a separately verified logical raw trigger; no interpolation. Nonnegative downstream bounds assume the saved confirmed footprint is downstream of its unique active publication.','Enqueue brackets use the monotone latest-enqueued E prefix; dequeue brackets use D=E-pending under verified contiguous FIFO input. Queue residence and processing intervals remain coarse witnesses, not exact timings. Source timestamps precede construction/enqueue. Pre-publication bounds include that unmeasured gap, filtering/algorithm work and waits. They are not pure queue waiting or function CPU/GIL/Qt shares.','Only original optical input/state is verified by the oracle. GUI/inference/SDK callbacks and thread scheduling are not replayed or attributed. Every case and prior failed quality gate remains.']
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print({k:dict(peak=v['peak']['pending'],downstream_upper_ms=v['maximum_downstream_upper_ms'],worst_event=v['max_total_event']) for k,v in result['cases'].items() if k.endswith('pair01_a')})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prior',type=Path,required=True);p.add_argument('--repeat',type=Path,required=True);p.add_argument('--oracle',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
