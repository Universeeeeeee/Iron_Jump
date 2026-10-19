"""Read-only readiness audit and descriptive common-frame timing, all cases retained."""
import hashlib
import json
from pathlib import Path
import statistics

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def unique_frames(rows):
    out={}
    for r in rows:
        key=(r['frame'],r['sample_time_s'])
        if key in out:raise ValueError('Duplicate frame identity')
        out[key]=r['wall_ms']
    return out

def main():
    prior=read(HERE/'state_result03.json');plan=read(HERE/'plan02.json');raw=HERE/'runs/evidence01'
    manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    names=[x['id'] for x in plan['cases']];maps={n:unique_frames(prior['cases'][n]['all_inference_frame_identity']) for n in names}
    common=set.intersection(*(set(v) for v in maps.values()));assert common
    cases={}
    for n in names:
        capture=raw/'runs/gui02'/n/'capture';m=read(capture/'measurement.json');w=read(capture/'workload_final.json');rows=w['rows']
        opened=rows['model_open'];ready=[x for x in rows['service_status'] if x['status']=='ready'];assert len(opened)==len(ready)==1
        assert opened[0]['end_ns']<=ready[0]['observed_ns']
        arm=m['armed_ns'];contact_ns=arm+round(prior['cases'][n]['first_contact_since_arm_s']*1e9)
        assert ready[0]['observed_ns']<contact_ns
        cases[n]=dict(model_open_end_since_arm_ms=(opened[0]['end_ns']-arm)/1e6,ready_since_arm_ms=(ready[0]['observed_ns']-arm)/1e6,
            ready_before_arm=ready[0]['observed_ns']<=arm,ready_before_contact_ms=(contact_ns-ready[0]['observed_ns'])/1e6,
            all_frame_count=len(maps[n]),common_frame_median_wall_ms=statistics.median(maps[n][k] for k in common))
    comparisons=[]
    for k in sorted(common):
        # Sequence strata describe the observed transition; they are not randomized arms.
        early=[maps[n][k] for n in names[:1]];later=[maps[n][k] for n in names[1:]]
        comparisons.append(dict(frame=k[0],source_time_s=k[1],first_median_wall_ms=statistics.median(early),later_seven_median_wall_ms=statistics.median(later),ratio=statistics.median(early)/statistics.median(later)))
    result=dict(exploratory_after_results=True,cases=cases,common_frames=len(common),common_frame_comparisons=comparisons,
        median_per_frame_early_to_late_ratio=statistics.median(x['ratio'] for x in comparisons),
        common_frames_early_median_exceeds_late=sum(x['ratio']>1 for x in comparisons),
        bindings={n:sha(HERE/n) for n in ['state_result03.json','plan02.json','readiness_alignment04.py']},
        limits=['Sequence strata were identified after outcomes; no causal effect, statistical independence, or A/B efficacy inferred.',
                'Common video metadata does not establish identical decoded pixels, model tracking state or preceding frame history. All original windows/endpoints remain in result01.',
                'Ready confirms adapter.open returned, not CPU readiness, completed warmup, low observer disturbance or steady performance.',
                'Every model is ready before first contact. Ready alone is not a demonstrated explanation for persistent contact slowdown.',
                'Existing fixed-work CPU/cycles records belong to a different protocol and cannot be assigned to these windows.'],primary_root_identified=False)
    with (HERE/'readiness_alignment04.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='common_frame_comparisons'},indent=2))

if __name__=='__main__':main()
