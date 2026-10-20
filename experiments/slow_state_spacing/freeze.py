import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((ROOT/'experiments/cpu_state_observation/plan01.json').read_text())
    p.pop('observation_rules');p.pop('scope');p.pop('sources')
    p['schedule']=[dict(id='initial',gap_seconds=None),dict(id='short01',gap_seconds=5),dict(id='long01',gap_seconds=300),
        dict(id='short02',gap_seconds=5),dict(id='short03',gap_seconds=5),dict(id='long02',gap_seconds=300)]
    p['cases']=[c['id'] for c in p['schedule']];p['case_variants']={n:'serial' for n in p['cases']}
    p['state_rules']=dict(slow_prepare_ms_min=4300,fast_prepare_ms_max=3500,slow_model_ms_min=30,fast_model_ms_max=26,
        basis='Existing fixed-work preparation and model timing gaps. Joint labels only; intermediate retained. Not GHz/CPU/GIL orfield-symptom gates.')
    p['spacing_rules']=dict(long_gap_seconds=300,maximum_launch_lateness_seconds=2,
        long_system_busy_median_percent_max=15,long_system_busy_max_percent_max=50,min_long_intervals=50,required_AC=1)
    p['decision']='Support only repeated recurrence: both long windows follow fast joint states and become slow joint states, both spacing/quietAC checks pass, all post-long short windows are fast. Otherwise cannot identify this5mincondition; never rule out longer gaps orother states.'
    p['budget']='Exactly6 new processes. No retry/optional extension, prime, native compute probe, GUI, SDK/device, human, USB orRun. One variable: interprocess elapsed gap. All original work/returns/threads/settings held constant.'
    p['failure_policy']='Stop after any target/identity/accounting/spacing/cleanup failure; retain live PID and locks on timeout, no automatic kill/restart.'
    p['dependency_sources']['experiments/cpu_state_observation/workload.py']=sha(ROOT/'experiments/cpu_state_observation/workload.py')
    p['sources']={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.suffix in ('.py','.ps1','.diff','.json') and f.name in
        ['workload.py','verify.py','spacing.py','classify.py','cohort.py','test_rules.py','freeze.py','preflight.py','reference01.json','launch.py','analyze.py','workload_changes01.diff']}
    p['reference_source_sha256']=sha(HERE/'reference01.json')
    p['goal']='Test a controlled no-target interval as a trigger of recurrent slow original fixed work; do not optimize the application.'
    p['old_native_stack_and_disturbance_failures_upgraded']=False
    with (HERE/'plan01.json').open('x') as f:json.dump(p,f,indent=2)
    print(json.dumps(dict(cases=p['schedule'],state_rules=p['state_rules']),indent=2))
