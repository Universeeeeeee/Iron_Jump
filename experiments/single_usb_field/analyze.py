"""Post-acquisition analysis only; never imported by live GUI or SDK process."""
import argparse,csv,hashlib,json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def stats(values):
    if not len(values):return {'count':0,'p95':None,'max':None}
    return {'count':len(values),'p95':float(np.percentile(values,95)),'max':float(max(values))}
def window(points,start,end):
    rows=[r for r in points if start<=r[0]<end]
    if len(rows)<3:return {'observations':len(rows),'insufficient':True}
    elapsed=(rows[-1][0]-rows[0][0])/1e9
    e=(rows[-1][5]-rows[0][5])/elapsed;c=(rows[-1][1]-rows[0][1])/elapsed
    ages=[(r[0]-r[4])/1e6 if r[4] is not None else 0 for r in rows]
    complete=[(r[0]-r[2])/1e6 for r in rows]
    device=np.array([(r[1]-rows[0][1])/1000 for r in rows]);slope=float(np.polyfit(device,complete,1)[0]) if np.ptp(device)>0 else None
    maximum=0.;begin=None;previous=None
    for r,age in zip(rows,ages):
        if r[3]>=100 and age>=100:
            if begin is None or previous is None or r[0]-previous>250000000:begin=r[0]
            maximum=max(maximum,(r[0]-begin)/1e9);previous=r[0]
        else:begin=previous=None
    return {'observations':len(rows),'observed_s':elapsed,'enqueued_fps':e,'consumer_fps':c,'throughput_gap_to_actual_fps':e-c,'pending':stats([r[3] for r in rows]),'oldest_pending_ms':stats(ages),'completed_receipt_age_ms':stats(complete),'age_slope_ms_per_device_second':slope,'heavy_observed_span_s':maximum,'max_observation_gap_ms':float(max(np.diff([r[0] for r in rows]))/1e6),'sustained_shortage':bool(elapsed>=2 and e>=990 and c<970 and maximum>=1 and slope is not None and slope>10)}

def analyze(folder):
    m=read(folder/'measurement.json');state=read(folder/'state.json');report=read(folder/'report.json');shutdown=read(folder/'shutdown.json');start=read(folder/'camera_record_start.json');end=read(folder/'camera_record_end.json')
    assert read(folder/'complete.json')['system_exit_code']==0 and not m['errors'] and not m['SDK_errors']
    assert not shutdown['errors'] and shutdown['SDK']['stops']>0 and not shutdown['readers']
    assert len(m['readers_at_start'])==1 and not m['readers_after_stop'] and m['threads']['consumer']!=m['threads']['gui']
    assert m['queue_final'][3]==m['queue_final'][7]==0
    assert m['record_stats']['frames_written']>0 and m['record_stats']['last_hresult']>=0 and m['prepared'] is not None
    with np.load(folder/'raw_frames.npz') as a:raw={k:a[k].copy() for k in a.files}
    with np.load(folder/'raw_archive.npz') as a:archive=a['bits'].copy();times=a['device_timestamps'].copy()
    samples=raw['sample_indices'];received=raw['received_ns'];ticks=np.rint(times*1000).astype(np.int64)
    assert len(samples)==len(set(samples.tolist())) and len(archive)==m['raw_total']==m['raw_retained']
    assert hashlib.sha256(archive.tobytes()).hexdigest()==m['raw_archive_sha256']
    lookup={int(v):k for k,v in enumerate(samples)};indices=np.array([lookup[int(v)] for v in ticks]);assert np.array_equal(archive,raw['bits'][indices])
    assert ticks[-1]==m['queue_final'][1]==m['queue_final'][5]
    continuous=bool(np.all(np.diff(samples)==1) and np.all(np.diff(ticks)==1) and np.all(raw['dropped_frames_before']==0))
    original_bits=archive.copy();bad=state['quality']['preflight']['bad_indices'];archive[:,bad]=0;usable=np.any(archive>0,axis=1)
    host_receipts=received[indices];formal=(host_receipts>=m['armed_ns'])&(host_receipts<m['stop_request_ns'])
    active=usable&formal;positions=np.flatnonzero(active)
    points=sorted(m['queue_common']+m['queue_samples'],key=lambda r:r[0]);windows={}
    ranges=[('whole_formal',m['armed_ns'],m['stop_request_ns']),('initial_empty',m['armed_ns'],m['armed_ns']+5000000000)]
    if len(positions):ranges.append(('contact_span',int(host_receipts[positions[0]]),int(host_receipts[positions[-1]])+1000000))
    clear=next((v['host_ns'] for v in m['marks'] if v['name']=='operator_clear'),None)
    if clear is not None:ranges.append(('operator_tail',clear,m['stop_request_ns']))
    elif len(positions):ranges.append(('observed_tail',int(host_receipts[positions[-1]])+1000000,m['stop_request_ns']))
    for label,a,b in ranges:
        w=window(points,a,b);mask=(host_receipts>=a)&(host_receipts<b)
        w.update(start_ns=int(a),end_ns=int(b),raw_frames=int(mask.sum()),usable_contact_fraction=float(usable[mask].mean()) if mask.any() else None)
        windows[label]=w
    bins=[]
    if formal.any():
        origin=int(ticks[np.flatnonzero(formal)[0]])
        for second in sorted(set(((ticks[formal]-origin)//1000).tolist())):
            mask=formal&((ticks-origin)//1000==second);fraction=float(usable[mask].mean());n=int(mask.sum())
            bins.append({'device_second':second,'samples':n,'usable_contact_fraction':fraction,'phase':'partial' if n<1000 else 'dense' if fraction>=.5 else 'empty' if fraction<=.01 else 'mixed'})
    # Video data itself may stay on Windows, while its CSV is always fetched.
    with (folder/'camera.csv').open() as f:camera=list(csv.DictReader(f))
    offsets=[int(v['offset']) for v in camera];lengths=[int(v['length']) for v in camera]
    assert all(b==a+n for a,n,b in zip(offsets,lengths,offsets[1:]))
    assert len(camera)==end['stats']['frames_written'] and sum(lengths)==end['stats']['bytes_written']
    summary=report['walking_summary' if m['mode']=='walk' else 'running_summary'];paint={int(k):v for k,v in m['paints'].items()};latencies=[]
    for event in summary['event_publications']:
        cid=event.get('contact_id');sample=event.get('touch_sample')
        if event.get('active') and cid in paint and sample in lookup:
            latencies.append({'contact_id':cid,'sample':sample,'receipt_to_paint_ms':(paint[cid]-int(received[lookup[sample]]))/1e6})
    initial=windows['initial_empty'];tail=next((v for k,v in windows.items() if 'tail' in k),None)
    scene_valid=bool(len(positions) and initial['usable_contact_fraction'] is not None and initial['usable_contact_fraction']<=.01 and tail and tail.get('observed_s',0)>=10 and tail['usable_contact_fraction'] is not None and tail['usable_contact_fraction']<=.01)
    errors=[v for v in state['quality']['events'] if v.get('code',v.get('kind')) in ('invalid_data','data_timeout','device_changed','counter_reset')]
    valid=continuous and not errors and scene_valid
    recovery=None
    if len(positions):
        last=int(host_receipts[positions[-1]]);r=next((r for r in points if last<=r[0]<m['stop_request_ns'] and r[3]==r[7]==0),None)
        if r is not None:recovery={'observed_upper_bound_ms':(r[0]-last)/1e6,'last_usable_contact_receipt_ns':last,'empty_witness_ns':r[0],'scope':'First sampled empty witness, not exact recovery; not a footstep accuracy assertion.'}
    pose_intervals=[]
    snapshots=[{'host_ns':m['armed_ns'],'visual':m['visual_start']}]+m['telemetry']+[{'host_ns':m['stop_request_ns'],'visual':m['visual_end']}]
    if len(positions):
        a=int(host_receipts[positions[0]]);b=int(host_receipts[positions[-1]])
        for left,right in zip(snapshots,snapshots[1:]):
            if right['host_ns']>a and left['host_ns']<b:
                pose_intervals.append({'start_ns':left['host_ns'],'end_ns':right['host_ns'],'valid_draws':right['visual']['valid_pose_draws']-left['visual']['valid_pose_draws'],'nodes_drawn':right['visual']['valid_nodes_drawn']-left['visual']['valid_nodes_drawn'],'links_drawn':right['visual']['valid_links_drawn']-left['visual']['valid_links_drawn']})
    pose_coverage=bool(pose_intervals and all(v['valid_draws']>0 for v in pose_intervals))
    output={'contact_pose_intervals':pose_intervals,'contact_pose_present_in_each_observed_interval':pose_coverage,'name':folder.name,'mode':m['mode'],'valid_field_protocol':bool(valid),'continuous_device_samples':continuous,'quality_acquisition_failures':errors,'scene_protocol_valid':scene_valid,'raw_formal_frames':len(ticks),'raw_total_with_preflight':len(samples),'duration_s':(m['stop_request_ns']-m['armed_ns'])/1e9,'bad_indices':bad,'formal_features':{'SDK_started':m['SDK_start']['starts']>0,'full_body_prepared':m['prepared'] is not None},'visual_formal':{k:m['visual_end'][k]-m['visual_start'][k] for k in m['visual_start']},'SDK':shutdown['SDK'],'record_stats':end['stats'],'camera_start_bracket_ns':[start['before_ns'],start['after_ns']],'windows':windows,'device_contact_bins':bins,'observed_recovery':recovery,'footprint_receipt_to_paint_ms':stats([v['receipt_to_paint_ms'] for v in latencies]),'footprint_timings':latencies,'report_event_publications':summary['event_publications'],'sustained_shortage_reproduced':bool(valid and any(v.get('sustained_shortage',False) for v in windows.values())),'limits':['One field passage is not stable repeated reproduction.','Original missing-step/effective-interval correctness remains separate.','SDK/full-body preparation does not prove valid pose throughout passage; inspect telemetry/video.','Batch retention and SDK logging overhead not independently calibrated.','Native CSV times have only start-clock bracket, not device-clock synchronization.','Receipt timestamps are after USB reading/assembly; original wire delivery time unknown.']}
    (folder/'analysis.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    return output
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);args=p.parse_args();result=analyze(args.folder)
    print(json.dumps({k:v for k,v in result.items() if k not in ('windows','device_contact_bins','footprint_timings','report_event_publications')},ensure_ascii=False,indent=2))
