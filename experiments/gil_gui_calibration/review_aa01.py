"""Describe all GUI A/A feasibility pairs without promoting them to field qualification."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from align_clock import mapping


read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def counters(record):
    assert record.get('case_pass') and not record['errors'] and not record['target_still_running']
    before,after=record['before'],record['after'];assert len(before)==len(after) and len(before)>=4
    assert len({(r['pid'],r['tid']) for r in before})==len(before)
    gui={r['pid'] for r in before if r['role']!='sdk'};sdk={r['pid'] for r in before if r['role']=='sdk'}
    assert gui=={record['target_pid']} and len(sdk)==1 and not gui&sdk
    totals={role:dict(cpu_ns=0,cycles=0,threads=0) for role in ('gui','consumer','reader','sdk')}
    for a,b in zip(before,after):
        assert a['active'] and b['active'] and (a['pid'],a['tid'],a['creation_100ns'],a['role'])==(b['pid'],b['tid'],b['creation_100ns'],b['role'])
        assert all(b[k]>=a[k] for k in ('cycles','user_100ns','kernel_100ns'))
        slot=totals[a['role']];slot['cpu_ns']+=(b['user_100ns']+b['kernel_100ns']-a['user_100ns']-a['kernel_100ns'])*100;slot['cycles']+=b['cycles']-a['cycles'];slot['threads']+=1
    assert all(totals[r]['threads']==1 for r in ('gui','consumer','reader'))
    clock=mapping(record['anchors']+[r[k] for group in (before,after) for r in group for k in ('start','end')]);assert clock['uncertainty_ns']<=1000000
    return dict(totals=totals,clock=clock)


def summarize(pairs):
    from scipy.stats import t
    keys=[(role,k) for role in ('consumer','gui','sdk') for k in ('cpu_ns','cycles')];family=len(keys);out={}
    for role,key in keys:
        values=[(a[role][key],b[role][key]) for a,b in pairs]
        if any(x<=0 or y<=0 for x,y in values):out[role+'_'+key]=dict(available=False,reason='Zero counter delta; no replacement or epsilon.');continue
        ratios=[math.log(y/x) for x,y in values];n=len(ratios)
        if n<2:out[role+'_'+key]=dict(available=False,reason='Fewer than2 complete pairs.');continue
        mean=statistics.mean(ratios);sd=statistics.stdev(ratios);half=float(t.ppf(1-.05/(2*family),n-1))*sd/math.sqrt(n)
        out[role+'_'+key]=dict(available=True,independent_pairs=n,log_ratio_sd=sd,geometric_relative_change=math.expm1(mean),simultaneous_ci_relative=[math.expm1(mean-half),math.expm1(mean+half)],raw_relative_changes=[y/x-1 for x,y in values])
    return out


def main(a):
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items())
    base=a.raw/'experiments/gil_gui_calibration';plan=read(base/'aa_plan01.json');frozen=read(base/'aa_frozen_sources01.json')['files']
    assert all(sha(a.raw/n)==h for n,h in frozen.items())
    stage=base/'runs/off_aa01';status=read(stage/'result01.json');assert status['plan_sha256']==sha(base/'aa_plan01.json')
    result=dict(capture_status=status,cases={},pairs=[],statistics={},actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,manifest_sha256=sha(a.raw/'manifest.json'),reviewer_sha256=sha(Path(__file__)))
    for name in status['cases']:
        record=read(stage/name/'record01.json');m=read(stage/name/'capture/measurement.json')
        result['cases'][name]=dict(**counters(record),camera=m['camera'],sdk=m['sdk'],pose_draws=m['pose_draws'],video_indices=m['video_indices'])
    numeric=[]
    for i in range(1,5):
        names=[f'pair{i:02d}_{side}' for side in ('a','b')]
        if not all(n in result['cases'] for n in names):continue
        x,y=(result['cases'][n] for n in names);ids_equal=x['video_indices']==y['video_indices'];thread_counts_equal=x['totals']['sdk']['threads']==y['totals']['sdk']['threads']
        result['pairs'].append(dict(pair=i,delivered_video_ids_equal=ids_equal,sdk_thread_count_equal=thread_counts_equal,camera=[x['camera'],y['camera']],pose_valid=[x['pose_draws']['valid'],y['pose_draws']['valid']],sdk_decisions=[x['sdk']['tracking_decisions'],y['sdk']['tracking_decisions']]))
        numeric.append((x['totals'],y['totals']))
    result['statistics']=summarize(numeric);result['all_four_pairs_complete']=len(numeric)==4 and status.get('all_fixed_cases_complete',False) and not status['errors']
    result['necessary_video_identity_gate']=result['all_four_pairs_complete'] and all(p['delivered_video_ids_equal'] for p in result['pairs'])
    result['limits']=['Exactly4 feasibility pairs; all kept including unmatched video/SDK work. Whole fresh-process pair is independent unit. Six Bonferroni Student-t log-ratio endpoints are descriptive and depend on parametric stationarity/independence. No3% equivalence or1% precision claim.','CPU deltas are selected retained native threads only; GUI process vision/decoder threads outside these roles are not included. SDK has its own PID/GIL; cycles are not frequency.','Camera frame identity is only a necessary workload check. Actual inference selection, GUI draws, SDK decisions and actual physical USB/camera acquisition remain unmatched/unqualified. No CPU/GIL/Qt shares or historical root attribution.','No observer was enabled. This cannot qualify4Hz sampling even if A/A intervals appear narrow. No human Walk should replace the missing calibration.']
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print({k:result[k] for k in ('all_four_pairs_complete','necessary_video_identity_gate','pairs','actual_load_disturbance_pass','field_attribution_ready')})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
