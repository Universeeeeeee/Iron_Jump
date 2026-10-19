"""Post-hoc source-aligned state review; no additional capture or causal shares."""
import hashlib
import json
from pathlib import Path
import statistics
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def spans(rows,start,end):
    if end<=start:raise ValueError('Empty or reversed interval')
    clipped=sorted((max(start,r['begin_ns']),min(end,r['end_ns'])) for r in rows if r['begin_ns']<end and r['end_ns']>start)
    merged=[]
    for a,b in clipped:
        if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],b)
        else:merged.append([a,b])
    full=[(r['end_ns']-r['begin_ns'])/1e6 for r in rows if start<=r['begin_ns'] and r['end_ns']<=end]
    return dict(overlap_calls=len(clipped),union_wall_ms=sum(b-a for a,b in merged)/1e6,fully_contained_calls=len(full),median_full_wall_ms=statistics.median(full) if full else None)

def main():
    import numpy as np
    sys.path.insert(0,str(ROOT/'experiments/gil_gui_analysis'))
    from temporal_review02 import validate_queue,completion_bracket
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json')
    assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan02.json');result=read(HERE/'result02.json');out={};logical=None
    for case in plan['cases']:
        name=case['id'];capture=raw/'runs/gui02'/name/'capture'
        m=read(capture/'measurement.json');w=read(capture/'workload_final.json');report=read(capture/'report.json')
        with np.load(capture/'raw_frames.npz') as z:
            indices=z['sample_indices'];received=dict(zip(map(int,indices),map(int,z['received_ns'])))
            usable=z['bits'].astype(bool)&z['valid_bits'].astype(bool)
            usable[:,report['report_config_snapshot']['device']['bad_indices']]=False
            contact=indices[np.any(usable,axis=1)&(indices>m['checked'])]
        bounds=(m['checked']+1,int(contact[0]),int(contact[-1])+1,int(indices[-1]))
        if logical is None:logical=bounds
        assert bounds==logical
        validate_queue(m,received)
        rows=w['rows'];calls=rows['adapter_calls'];inferences=rows['inferences']
        assert len(calls)==len(inferences) and all(x['error'] is None for x in calls)
        links=[]
        for r in inferences:
            info=r['record'];matches=[a for a in calls if a['tid']==r['tid'] and a['timestamp_ms']==round(info['frame_timestamp_s']*1000)]
            assert len(matches)==1
            a=matches[0];assert info['inference_start_s']*1e9<=a['begin_ns']<=a['end_ns']<=info['inference_end_s']*1e9<=r['observed_ns']
            links.append(dict(frame=info['metadata']['frame_index'],sample_time_s=info['metadata']['sample_time_s'],wall_ms=(a['end_ns']-a['begin_ns'])/1e6))
        phases={}
        for label,left,right in zip(('pre_contact','contact_envelope','post_contact'),bounds,bounds[1:]):
            start,end=received[left],received[right]
            q=[r for r in m['queue_common']+m['queue_samples'] if start<=r[0]<end]
            phases[label]=dict(source_samples=[left,right],duration_ms=(end-start)/1e6,adapter=spans(calls,start,end),gui_io=spans(rows['gui_io'],start,end),observed_deque_peak=max((r[3] for r in q),default=None))
        transitions=[]
        for threshold in (100,1000):
            matches=sorted((r for r in m['queue_common']+m['queue_samples'] if r[0]>=m['armed_ns'] and r[3]>=threshold),key=lambda r:r[0])
            if matches:
                r=matches[0];transitions.append(dict(threshold=threshold,first_observed_host_s=(r[0]-m['armed_ns'])/1e9,completed_sample=r[1],received_sample=r[5],observed_pending=r[3]))
        a=completion_bracket(m['queue_common'],bounds[1]);b=completion_bracket(m['queue_common'],bounds[2]-1)
        out[name]=dict(variant=case['variant'],phases=phases,first_observed_thresholds=transitions,
            contact_completion_span_ms_bounds=[max(0,b[0]-a[1])/1e6,(b[1]-a[0])/1e6],
            contact_input_span_ms=(received[bounds[2]-1]-received[bounds[1]])/1e6,
            model_open_ms=[(x['end_ns']-x['begin_ns'])/1e6 for x in rows['model_open']],
            full_adapter_median_ms=statistics.median(x['wall_ms'] for x in links),
            first_inference_since_arm_s=(calls[0]['begin_ns']-m['armed_ns'])/1e9,
            first_contact_since_arm_s=(received[bounds[1]]-m['armed_ns'])/1e9,
            all_inference_frame_identity=links,
            max_publication_to_paint_upper_ms=max(e['publication_to_paint_nonnegative_bounds_ms'][1] for e in result['cases'][name]['all_contact_events']))
    result=dict(cases=out,source_sha256=sha(Path(__file__)),manifest_sha256=sha(raw/'manifest.json'),input_result_sha256=sha(HERE/'result02.json'),
        exploratory_after_results=True,root_cause_or_fix_complete=False,
        limits=['All eight cases retained. This is post-hoc description, not another intervention or significance test.',
                'Adapter and GUI I/O spans are wall time including scheduling/GIL/native waits, not CPU time or GIL ownership. Union prevents nested span double-counting.',
                'Phases are fixed logical source boundaries using actual receipt clocks. Contact envelope includes gaps; post-contact includes unfinished earlier work.',
                'Sampled queue transitions are first observed crossings, not exact onset. Completion spans are conservative witness bounds, not exact batch measurements.',
                'Different selected video frames and dynamic work remain. No continuous frequency, competing-system-task, or per-thread CPU/cycles records were acquired in this AB.',
                'Common diagnostic disturbance remains unqualified; simulated native SDK and offline replay limit field generalization.'])
    with (HERE/'state_result03.json').open('x') as f:json.dump(result,f,indent=2)
    for name,c in out.items():print(name,json.dumps({k:v for k,v in c.items() if k!='all_inference_frame_identity'}))

if __name__=='__main__':main()
