"""Compare every new outcome with the preserved cohort, without restart causality."""
import argparse
import json
from pathlib import Path
from review_aa01 import read,sha,counters,summarize
from review_progress01 import queue_metrics,publications,work_alignment


def main(a):
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items())
    base=a.raw/'experiments/gil_gui_calibration';plan=read(base/'repeat_plan01.json');frozen=read(base/'repeat_frozen01.json')['files'];assert all(sha(a.raw/n)==h for n,h in frozen.items())
    status=read(base/'runs/restart_repeat01/result01.json');assert status['plan_sha256']==sha(base/'repeat_plan01.json')
    previous=read(a.previous);rules=read(Path(__file__).parent/'repeat_analysis_plan01.json')
    assert sha(a.previous)==rules['prior_progress_result_sha256'] and sha(Path(__file__))==rules['reviewer_sha256']
    phase=next(g for g in read(base/'phases.json')['walk'] if g['phase']=='dense')
    result=dict(status=status,cases={},pairs=[],comparison=[],actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,manifest_sha256=sha(a.raw/'manifest.json'),reviewer_sha256=sha(Path(__file__)))
    for name in plan['cases']:
        folder=base/'runs/restart_repeat01'/name
        if not (folder/'record01.json').exists():
            result['cases'][name]=dict(case_pass=False,not_attempted_or_no_final_record=True);continue
        record=read(folder/'record01.json')
        if not record.get('case_pass') or record['errors'] or record['target_still_running']:
            result['cases'][name]=dict(case_pass=False,errors=record['errors'],target_still_running=record['target_still_running']);continue
        m=read(folder/'capture/measurement.json');report=read(folder/'capture/report.json');native=counters(record)
        result['cases'][name]=dict(case_pass=True,**native,queue=queue_metrics(m,phase['start'],phase['end']),publication=publications(m,report),counter_work=work_alignment(record,m,native['clock']),camera=m['camera'],sdk=m['sdk'],pose_draws=m['pose_draws'],video_indices=m['video_indices'])
        old=previous['cases'][name]
        result['comparison'].append(dict(case=name,old_max_pending=old['queue']['whole_case_max_pending'],new_max_pending=result['cases'][name]['queue']['whole_case_max_pending'],old_paint_max_ms=old['publication']['max_ms'],new_paint_max_ms=result['cases'][name]['publication']['max_ms']))
    numeric=[]
    for i in range(1,5):
        x,y=(result['cases'][f'pair{i:02d}_{side}'] for side in ('a','b'))
        if not x['case_pass'] or not y['case_pass']:continue
        result['pairs'].append(dict(pair=i,delivered_video_ids_equal=x['video_indices']==y['video_indices'],sdk_thread_count_equal=x['totals']['sdk']['threads']==y['totals']['sdk']['threads'],pose_valid=[x['pose_draws']['valid'],y['pose_draws']['valid']],sdk_decisions=[x['sdk']['tracking_decisions'],y['sdk']['tracking_decisions']]))
        numeric.append((x['totals'],y['totals']))
    result['statistics']=summarize(numeric)
    result['all_eight_cases_pass']=len(numeric)==4 and status.get('all_fixed_cases_complete',False) and not status['errors']
    result['necessary_video_identity_gate']=result['all_eight_cases_pass'] and all(p['delivered_video_ids_equal'] for p in result['pairs'])
    result['limits']=['User-requested new independent repeat; no pooling, trimming, success-driven extensions or replacing the earlier3391-frame backlog window. Every outcome/not-attempted case retained.','Reported restart scope/duration unspecified. Fixed saved optical/video input does not read the physical grating. Real SDK interacts with the camera. No isolated causal restart/power/temperature/USB inference.','No extra smoke before this repeat; earlier cohort had a prior smoke. Cross-session timing, warm-up and ordinary background differ. A preexisting terminal-event waiter blocks throughout; no mid-case status polling. Prior pair04_b status-query caveat remains.','Four whole fresh-process pairs only. Same six descriptive counter endpoints/clock gates; no3% equivalence or1% precision certification. GUI role excludes other GUI process vision/decoder threads. Cycles are not physical frequency.','Same-host counter windows can cover different consumer sample progress. No complete simultaneous GIL owner/waiter stacks, ETW loss/scheduling shares or CPU/GIL/Qt quantitative attribution.']
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print({k:result[k] for k in ('all_eight_cases_pass','necessary_video_identity_gate','comparison')})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--previous',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
