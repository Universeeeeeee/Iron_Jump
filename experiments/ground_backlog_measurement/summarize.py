"""Offline recheck; run only after all trials have stopped."""
import csv,hashlib,json
from pathlib import Path
import numpy as np
from analyze import metrics
from semantics import read,HERE

def main():
    results=[];native=[];rows=[];phases=[];cadence=[];busy=0
    for folder in sorted((HERE/'runs').iterdir()):
        if folder.name=='smoke_walk' or not (folder/'measurement.json').exists():continue
        r=metrics(folder);m=read(folder/'measurement.json');results.append(r)
        count=sum(q[3]==0 and q[7]>0 for q in m['queue_samples']);busy+=count
        assert m['queue_common'][-1][9]=='empty'
        d=next(v for v in r['phases'] if v['phase']=='dense')
        rows.append({'name':r['name'],'mode':r['mode'],'load':r['load'],'dense_consumer_fps':d['consumer_fps'],'dense_arrival_fps':d['actual_arrival_fps'],'age_slope_ms_per_device_second':d['completion_age_slope_ms_per_device_second'],'pending_p95':d['queue_depth']['p95'],'oldest_pending_age_p95_ms':d['oldest_pending_age_ms']['p95'],'heavy_span_s':d['heavy_queue_observed_span_s'],'first_observed_empty_ms':r['first_observed_empty_s']*1000 if r['first_observed_empty_s'] is not None else None,'footprint_p95_ms':r['footprint_p95_ms'],'footprint_max_ms':r['footprint_max_ms'],'native_callback_fps':r['native'].get('formal_callback_fps'),'representative_consumer_shortage':r['representative_consumer_shortage'],'empty_deque_but_busy_samples':count})
        phases.extend({'name':r['name'],'mode':r['mode'],**g} for g in r['phases'])
        arr=np.array(m['arrivals'],dtype=np.int64);cadence_phases=[]
        for g in r['phases']:
            a=arr[(arr[:,2]>=g['start'])&(arr[:,2]<g['end'])];lag=(a[:,0]-a[:,1])/1e6
            cadence_phases.append({'phase':g['phase'],'start':g['start'],'end':g['end'],'source_emission_lateness_p95_ms':float(np.percentile(lag,95)),'source_emission_lateness_max_ms':float(max(lag)),'actual_arrival_fps':g['actual_arrival_fps'],'consumer_fps':g['consumer_fps']})
        cadence.append({'name':r['name'],'phase_cadence':cadence_phases})
        if r['load']=='hardware':
            h=r['native']['hardware'];meta=read(folder/'native_usb_metadata.json')
            with np.load(folder/'native_usb_frames.npz') as a:
                n=len(a['sample_indices']);assert n==h['frames']==len(meta['frames']) and meta['algorithm_input'] is False
                assert np.all(np.diff(a['sample_indices'])==1) and np.all(np.diff(a['received_ns'])>=0)
                assert np.array_equal(a['bits'],1-np.unpackbits(a['wire'],axis=1,bitorder='little'))
                assert len({v['stream_id'] for v in meta['frames']})==1 and meta['frames'][0]['stream_id']==h['stream_id']
                assert not h['issues'] and h['stop_gated_and_closed'] and not np.any(a['dropped_frames_before'])
                gaps=np.diff(a['received_ns'])/1e6
                native.append({'name':folder.name,'frames':n,'delivered_fps':h['delivered_fps'],'formal_delivered_fps':h['formal_delivered_fps'],'drop_total':0,'raw_bits_equal_wire_inversion':True,'sample_indices_contiguous':True,'Python_assembly_receipt_gap_p95_ms':float(np.percentile(gaps,95)),'Python_assembly_receipt_gap_max_ms':float(max(gaps)),'contact_bits_per_frame_p50':float(np.median(a['bits'].sum(axis=1))),'contact_bits_per_frame_max':int(a['bits'].sum(axis=1).max()),'background_only':True})
    qualification={}
    for mode in ('walk','run'):
        trials=[r for r in results if r['load']=='hardware' and r['mode']==mode]
        assert len(trials)==3
        qualification[mode]={'trials':len(trials),'passes':sum(r['representative_consumer_shortage'] for r in trials),'all_pass':all(r['representative_consumer_shortage'] for r in trials)}
    eligible=all(v['all_pass'] for v in qualification.values())
    result={'semantic_reverified_trials':len(results),'new_AA_started':False,'AB_started':False,'eligible_load_found':eligible,'hardware_qualification':qualification,'empty_deque_but_busy_detail_samples':busy,'trials':results}
    assert not eligible,'Qualified workload needs A/A; do not publish an automatic stop conclusion'
    result['reason']='Real USB restored a missing original workload and produced single-trial shortage, but did not meet the predeclared three-of-three repeatability gate. No new A/A or A/B; no candidate benefit claim.'
    (HERE/'final_results.json').write_text(json.dumps(result,indent=2)+'\n')
    (HERE/'source_cadence.json').write_text(json.dumps(cadence,indent=2)+'\n')
    (HERE/'final_phases.json').write_text(json.dumps(phases,indent=2)+'\n')
    (HERE/'native_usb_recheck_final.json').write_text(json.dumps(native,indent=2)+'\n')
    with (HERE/'final_results.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:v for k,v in result.items() if k!='trials'},indent=2))
if __name__=='__main__':main()
