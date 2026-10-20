"""All fixed windows and legacy gates; A/A variance is not observer calibration."""
import hashlib,json,math,statistics,sys
from pathlib import Path
from metrics import measure,read
from scipy.stats import t
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/gui_qos_candidate'));from decision import decide
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def aa_variance(cases):
    if len(cases)!=4:raise ValueError('Exactly four fixed A/A cases required')
    values=[v['scheduled_max_ms'] for v in cases]
    if any(v<=0 for v in values):raise ValueError('Invalid latency')
    logs=[math.log(v) for v in values];sd=statistics.stdev(logs);half=float(t.ppf(.975,3))*sd/2
    return dict(scheduled_max_ms=values,log_sample_sd=sd,geometric_mean_ms=math.exp(statistics.mean(logs)),approximate_95pct_mean_relative_halfwidth=math.expm1(half),
        scope='Four sequential same-backend windows; stationarity/independence not established. Natural variability estimate only, not OFF/ON or total observer-disturbance calibration.',old_3pct_1pct_gate_still_failed=True)

if __name__=='__main__':
    plan=read(HERE/'plan01.json');archive=HERE/'runs/evidence01';manifest=read(archive/'manifest01.json');assert all(sha(archive/n)==v for n,v in manifest.items())
    assert all(sha(archive/n)==v for n,v in plan['sources'].items())
    original=ROOT/'experiments/session_isolation_throughput/runs/recorded_source01.npz';assert sha(original)==plan['input_sha256']['raw_frames.npz']
    stage=archive/'runs/cohort01';status=read(stage/'status.json');cases={}
    for case in plan['cases']:
        folder=stage/case['id']
        if not (folder/'record.json').exists():cases[case['id']]=dict(not_attempted=True);continue
        record=read(folder/'record.json')
        if record.get('errors') or record.get('target_still_running') or not record.get('complete'):cases[case['id']]=dict(failed=True,record=record);continue
        cases[case['id']]=measure(folder/'capture',original)
    complete=status['complete'] and not status['errors'] and all('scheduled_max_ms' in v for v in cases.values())
    pairs=[]
    if complete:
        for pair in plan['pairs']:
            a,b=cases[pair['original']],cases[pair['isolated']]
            matched=a['context']['foreground_gui']==b['context']['foreground_gui'] and a['context']['policy']==b['context']['policy']
            pairs.append((dict(a,qualified=matched),dict(b,qualified=matched)))
    result=dict(cases=cases,all_cases_complete=complete,aa=aa_variance([cases[n] for n in plan['aa_cases']]) if complete else None,symptom_decision=decide(pairs) if complete else None,
        actual_load_disturbance_pass=False,primary_root_identified=False,field_fix_verified=False,formal_program_changed=False,
        scope='Fixed shared-GUI saved-input whole measurement-process boundary including necessaryIPC and native scheduling effects; not exclusiveGIL causality.',
        limits=['No cases replaced or added. Failed cases stay failed.','Old3%/1% and native-stack qualification failures remain; no GIL/CPU shares or zero-observer counterfactual.','Actual work/frame selection retained as outcomes, not posthoc matched.','Same process priority/configuration andGUI-foreground patterns at six checkpoints are required, not continuous scheduling coverage.','A/A natural variance is not OFF/ON observer perturbation.','Original-return unconfirmed model cleanup retained separately from final observer tail.'],bindings=dict(plan_sha256=sha(HERE/'plan01.json'),archive_sha256=sha(HERE/'evidence01.zip'),analyzer_sha256=sha(Path(__file__))))
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(complete=complete,aa=result['aa'],decision=result['symptom_decision'],cases={n:{k:v.get(k) for k in ('backend','scheduled_max_ms','observed_queue_lower','queue_upper','failed','not_attempted')} for n,v in cases.items()}),indent=2))
