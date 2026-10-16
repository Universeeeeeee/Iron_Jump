"""Offline live-single-source validation and predeclared shortage classification."""
import csv,hashlib,json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def stats(x):return {'p50':float(np.median(x)),'p95':float(np.percentile(x,95)),'max':float(max(x))}
def phase(folder):
    m=read(folder/'measurement.json');report=read(folder/'report.json');pair=read(folder.parent/'pair.json')
    assert not m['errors'] and not m['SDK_errors'] and not pair['errors'] and not pair['SDK_errors']
    assert m['threads']['consumer']!=m['threads']['gui'] and m['worker_class']=='hardware.usb_worker.UsbWorker'
    assert m['qt_platform']=='windows' and len(m['readers_at_start'])==1 and not m['readers_after_stop'] and not pair['readers_after_all']
    assert m['features']=={'camera_enabled':True,'SDK_checked':True,'pose_checked':True,'vision_alive':True,'recording':False}
    assert m['SDK_start']['starts']>0 and pair['SDK']['stops']>0
    assert m['queue_final'][3]==m['queue_final'][7]==0
    with np.load(folder/'raw_archive.npz') as a:bits=a['bits'].copy();device_times=a['device_timestamps'].copy()
    assert len(bits)==m['raw_total']==m['raw_retained'] and bits.shape[1]==768
    assert hashlib.sha256(bits.tobytes()).hexdigest()==m['state']['raw_archive_sha256']
    ticks=np.rint(device_times*1000).astype(np.int64);contiguous=bool(np.all(np.diff(ticks)==1))
    assert ticks[-1]==m['queue_final'][1]==m['queue_final'][5]
    bad=m['state']['quality']['preflight']['bad_indices'];bits[:,bad]=0
    usable=bits.sum(axis=1);visual={k:m['visual_end'][k]-m['visual_start'][k] for k in m['visual_start']}
    assert visual['renders']>0 and visual['disabled_calls']==0
    duration=(m['stop_request_ns']-m['armed_ns'])/1e9
    summary_key='walking_summary' if m['mode']=='walk' else 'running_summary';events=report[summary_key]['event_publications']
    issues=[e for e in m['state']['quality']['events'] if e.get('code',e.get('kind')) in ('invalid_data','data_timeout','device_changed','counter_reset')]
    valid=contiguous and not issues and (m['smoke'] or duration>=29.9) and not any(e['active'] for e in events)
    out={'name':folder.parent.name+'/'+folder.name,'mode':m['mode'],'phase':m['phase'],'pid':m['pid'],'duration_s':duration,'valid_empty_phase':bool(valid),'contiguous_device_samples':contiguous,'quality_acquisition_failures':issues,'raw_frames':len(bits),'raw_first_sample':int(ticks[0]),'raw_last_sample':int(ticks[-1]),'usable_nonempty_frames':int(np.count_nonzero(usable)),'usable_nonempty_fraction':float(np.mean(usable>0)),'max_usable_contact_bits':int(max(usable)),'active_event_count':sum(e['active'] for e in events),'visual_formal':visual,'preview_render_fps':visual['renders']/duration,'effective_pose_draw_fps':visual['valid_pose_draws']/duration,'native_frames_formal':m['native_end']['frames']-m['native_start']['frames'],'native_fps_formal':(m['native_end']['frames']-m['native_start']['frames'])/duration,'SDK_reasons_formal':{k:v-m['SDK_reasons_start'].get(k,0) for k,v in m['SDK_reasons_end'].items()},'windows':[]}
    points=sorted(m['queue_common']+m['queue_samples'],key=lambda r:r[0])
    first_received=min(r[2] for r in points if r[2]>0)
    for label,start,end in [('first_USB_11s',first_received,first_received+11000000000),('initial_formal_11s',m['armed_ns'],min(m['armed_ns']+11000000000,m['stop_request_ns'])),('later_formal',m['armed_ns']+11000000000,m['stop_request_ns'])]:
        rows=[r for r in points if start<=r[0]<end]
        if len(rows)<3:continue
        dt=(rows[-1][0]-rows[0][0])/1e9;enq=(rows[-1][5]-rows[0][5])/dt;fps=(rows[-1][1]-rows[0][1])/dt
        q=np.array([r[3] for r in rows]);age=np.array([0 if r[4] is None else (r[0]-r[4])/1e6 for r in rows]);completion=np.array([(r[0]-r[2])/1e6 for r in rows]);slope=float(np.polyfit([(r[1]-rows[0][1])/1000 for r in rows],completion,1)[0])
        span=0.;begin=None;previous=None
        for r,v in zip(rows,age):
            if r[3]>=100 and v>=100:
                if begin is None or previous is None or r[0]-previous>250000000:begin=r[0]
                span=max(span,(r[0]-begin)/1e9);previous=r[0]
            else:begin=previous=None
        shortage=enq>=990 and fps<970 and span>=1 and slope>10
        out['windows'].append({'window':label,'observed_s':dt,'enqueued_fps':enq,'consumer_fps':fps,'pending':stats(q),'oldest_pending_ms':stats(age),'completed_receipt_age_ms':stats(completion),'age_slope_ms_per_device_second':slope,'heavy_queue_observed_span_s':span,'max_observation_gap_ms':max(np.diff([r[0] for r in rows]))/1e6,'sustained_shortage':bool(shortage),'interpretable_as_formal_camera_ready':label!='first_USB_11s'})
    return out

def main():
    records=[]
    for parent in sorted((HERE/'runs').glob('pair_*')):
        assert read(parent/'complete.json')['system_exit_code']==0
        for name in ('cold','warm'):records.append(phase(parent/name))
    any_formal=[r for r in records if r['valid_empty_phase'] and any(w['window']!='first_USB_11s' and w['sustained_shortage'] for w in r['windows'])]
    initial=[r for r in records if r['valid_empty_phase'] and any(w['window']=='initial_formal_11s' and w['sustained_shortage'] for w in r['windows'])]
    result={'formal_phase_count':len(records),'formal_empty_shortage_reproduced':bool(any_formal),'formal_reproducing_phase_names':[r['name'] for r in any_formal],'initial_empty_reproduced':bool(initial),'reproducing_phase_names':[r['name'] for r in initial],'native_trace_started':False,'candidate_AB_started':False,'trials':records}
    (HERE/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    rows=[]
    for r in records:
        w=next(w for w in r['windows'] if w['window']=='initial_formal_11s')
        rows.append({'name':r['name'],'mode':r['mode'],'phase':r['phase'],'valid':r['valid_empty_phase'],'consumer_fps':w['consumer_fps'],'enqueued_fps':w['enqueued_fps'],'pending_p95':w['pending']['p95'],'pending_max':w['pending']['max'],'oldest_pending_p95_ms':w['oldest_pending_ms']['p95'],'age_slope':w['age_slope_ms_per_device_second'],'heavy_span_s':w['heavy_queue_observed_span_s'],'reproduced':w['sustained_shortage'],'render_fps':r['preview_render_fps'],'effective_pose_draws':r['visual_formal']['valid_pose_draws']})
    if rows:
        with (HERE/'results.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
    print(json.dumps({k:v for k,v in result.items() if k!='trials'},indent=2))
if __name__=='__main__':main()
