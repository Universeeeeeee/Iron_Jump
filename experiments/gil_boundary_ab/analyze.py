"""All paired dynamic-work outcomes retained; no sampler-share attribution."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def p95(values):
    if not values:raise ValueError('No active-contact latency measurements')
    return sorted(values)[math.ceil(.95*len(values))-1]

def compare_pairs(pairs):
    from scipy.stats import t
    if len(pairs)!=4:raise ValueError('Fixed protocol requires all4 pairs')
    result={}
    for endpoint in ('max_latency_ms','p95_latency_ms'):
        values=[(a[endpoint],b[endpoint]) for a,b in pairs]
        if any(a<=0 or b<=0 for a,b in values):raise ValueError('Invalid latency; no epsilon/replacement')
        ratios=[math.log(b/a) for a,b in values];mean=statistics.mean(ratios);half=float(t.ppf(1-.05/(2*2),3))*statistics.stdev(ratios)/2
        result[endpoint]=dict(original=[a for a,b in values],candidate=[b for a,b in values],candidate_minus_original_ms=[b-a for a,b in values],raw_relative_change=[b/a-1 for a,b in values],geometric_relative_change=math.expm1(mean),simultaneous_t_interval_relative=[math.expm1(mean-half),math.expm1(mean+half)])
    return result

if __name__=='__main__':
    import numpy as np
    sys.path.insert(0,str(ROOT/'experiments/gil_observation_termination'));from queue_bounds import bound_deque
    sys.path.insert(0,str(ROOT/'experiments/gil_gui_analysis'));from temporal_review02 import event_bounds
    spec=importlib.util.spec_from_file_location('original_full_semantics',ROOT/'experiments/gil_workload_observation/verify.py');semantics=importlib.util.module_from_spec(spec);spec.loader.exec_module(semantics)
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'ab_plan01.json');assert all(sha(raw/n)==v for n,v in plan['sources'].items())
    reference=ROOT/'experiments/gil_workload_observation/runs/evidence02/runs/observation02/off_a/capture'
    mapping=read(ROOT/'experiments/gil_gui_analysis/publication_map02.json');triggers={x['event']['event_id']:x for x in mapping['trigger_events']}
    stage=raw/'runs/ab01';status=read(stage/'status.json');cases={}
    for case in plan['cases']:
        folder=stage/case['id'];capture=folder/'capture'
        if not (folder/'record.json').exists():cases[case['id']]=dict(not_attempted=True);continue
        record=read(folder/'record.json')
        if not record.get('complete') or record['errors'] or record['target_still_running']:cases[case['id']]=dict(failed=True,record=record);continue
        m=semantics.semantic_check(capture,reference);report=read(capture/'report.json');w=read(capture/'workload_final.json');final=read(capture/'finalization.json');active=read(capture/'activation.json');backend=read(capture/'sdk_backend.json')
        assert active['variant']==case['variant'] and active['candidate_installed']==(case['variant']=='candidate') and active['candidate_sha256']==plan['candidate_sha256'] and active['original_source_file_unchanged']
        assert final['metadata_finalization_pass'] and all(final['checks'].values()) and backend['backend']=='simulated_native_SDK' and backend['serve_returncode']==0 and backend['no_native_device_opened']
        assert m['native']['profile']=='fixed' and m['native']['callbacks']==0 and not m['native']['hardware']
        with np.load(capture/'raw_frames.npz') as data:
            indices=data['sample_indices'];assert np.array_equal(indices,np.arange(int(indices[0]),int(indices[-1])+1));received={int(n):int(t) for n,t in zip(indices,data['received_ns'])}
        queue=bound_deque(sorted([[x[0],x[5],x[3]] for x in m['queue_common']+m['queue_samples']]),int(indices[0]),int(indices[-1]))
        events=event_bounds(m,report,received,triggers);latencies=[e['source_touch_to_paint_ms'] for e in events];assert len(events)==sum(x['active'] for x in report['walking_summary']['event_publications'])
        arrivals={int(n):(int(now),int(due)) for now,due,n in m['arrivals']};assert len(arrivals)==len(m['arrivals'])==len(received)
        assert all(arrivals[n][0]==stamp for n,stamp in received.items())
        for event in events:
            now,due=arrivals[event['touch_sample']]
            event['touch_delivery_lateness_ms']=(now-due)/1e6
            event['scheduled_replay_touch_to_paint_ms']=event['source_touch_to_paint_ms']+event['touch_delivery_lateness_ms']
        maximum=max(latencies);quantile=p95(latencies)
        cases[case['id']]=dict(variant=case['variant'],complete_semantics_exact=True,max_latency_ms=maximum,p95_latency_ms=quantile,queue=queue,all_contact_events=events,
                              baseline_severe_reproduced=queue['combined_observed_deque_peak_lower_bound']>=1000 and maximum>=1000,
                              exploratory_scheduled_max_ms=max(e['scheduled_replay_touch_to_paint_ms'] for e in events),
                              exploratory_scheduled_p95_ms=p95([e['scheduled_replay_touch_to_paint_ms'] for e in events]),
                              formal_max_delivery_lateness_ms=max((now-due)/1e6 for n,(now,due) in arrivals.items() if n>m['checked']),
                              work=dict(video=len(m['video_indices']),inference=len(w['rows']['inferences']),relay=len(w['rows']['relay_packets']),sdk=m['sdk'],draws=m['pose_draws'],camera=m['camera']),
                              model_finalization_pass=True,original_return_confirmed=final['application_return_model_confirmed'],model_close_wall_ms=[(x['end_ns']-x['begin_ns'])/1e6 for x in w['rows']['model_close']])
    complete=status.get('complete',False) and not status['errors'] and all(x.get('complete_semantics_exact') for x in cases.values())
    pairs=[(cases[p['original']],cases[p['candidate']]) for p in plan['pairs']] if complete else []
    result=dict(cases=cases,all_fixed_cases_complete=complete,all_originals_severe=complete and all(a['baseline_severe_reproduced'] for a,b in pairs),
                paired_latency=compare_pairs(pairs) if complete else None,statistics_withheld=not complete,
                queue_pair_bounds=[dict(original=a['queue'],candidate=b['queue']) for a,b in pairs],
                exploratory_scheduled_latency_pairs=[dict(original_max_ms=a['exploratory_scheduled_max_ms'],candidate_max_ms=b['exploratory_scheduled_max_ms'],original_p95_ms=a['exploratory_scheduled_p95_ms'],candidate_p95_ms=b['exploratory_scheduled_p95_ms']) for a,b in pairs],
                scope='Authorized4-pair total intervention effect in original GUI/model replay with common simulated SDK and common diagnostics. Dynamic inference/SDK/draw work changes retained as outcomes.',
                limits=['Four-pair t intervals assume stationary independent approximately normal log-ratios; not a distribution-free guarantee.','Simulated native SDK does not establish actual device or physical SDK behavior.','No profiler percentages, GIL wait shares or exclusive CPU contribution inferred.','Original3%/1% observer and native stack qualification failures stay unchanged. No production fix or human test performed.'],
                primary_root_identified=False,actual_load_disturbance_pass=False,field_attribution_ready=False)
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(all_fixed_cases_complete=complete,all_originals_severe=result['all_originals_severe'],paired_latency=result['paired_latency'],case_metrics={n:{k:v.get(k) for k in ('variant','max_latency_ms','p95_latency_ms','queue','work')} for n,v in cases.items()}),indent=2))
