"""Four new OFF/OFF pairs; prior one-pair boundary evidence is excluded."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    old=HERE.parent/'fixed_work_accounting';plan=json.loads((old/'plan01.json').read_text())
    pairs=[[f'pair{i:02d}_a',f'pair{i:02d}_b'] for i in range(1,5)]
    dependencies=['experiments/fixed_work_accounting/'+n for n in ('run.py','counters.py','logical_clock.py')]+['experiments/fixed_concurrent_work/verify.py']
    plan.update(cases=[n for pair in pairs for n in pair],pairs=pairs,dependency_sources={n:sha(ROOT/n) for n in dependencies},
                sources={p.name:sha(p) for p in HERE.glob('*.py')},prior_boundary_plan_sha256=sha(old/'plan01.json'),prior_boundary_result_sha256=sha(old/'result01.json'),
                scope='Exactly4 new fresh-process OFF/OFF pairs of qualified fixed consumer+model task bundle. Sampler/ETW OFF throughout, common recorder/counter/retention ON. No GUI, SDK, live camera/USB, human, Run or optimization AB.',
                statistics=dict(independent_unit='Whole fresh-process pair, not individual threads/blocks/model calls.',endpoints=['wall_ns','cpu_ns','cycles'],wall_endpoint='Midpoint of saved whole-bundle OS-read brackets; every pair bracket ratio retained separately.',
                                family_alpha=.05,method='Bonferroni simultaneous Student-t intervals of pair log ratios; descriptive four-pair pilot with parametric independence/stationarity assumptions.',
                                retain_all_cases=True,optional_extension=False,outlier_removal=False,performance_detrending=False,cycle_normalization=False,
                                future_planning='Max endpoint log-ratio SD; once-only8..24 prospective pair count planning for log(1.01) half-width. Planning only, no ON run launched.',
                                original_3pct_1pct_acceptance_unchanged=True,common_observer_absolute_cost_unknown=True),
                checks=plan['checks']+['Every8 full input/model/report identities and complete process-accounting boundaries must pass; otherwise statistics withheld.',
                                      'Original boundary-qualification pair is excluded. No matching subset, no reordering after results, no extra case on a failure.',
                                      'Compute all4 raw pair differences including >15%; never interpret OFF/OFF variation as observer bias or claim controlled/dynamic field qualification.'])
    assert json.loads((old/'result01.json').read_text())['boundary_qualification_pass']
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    with zipfile.ZipFile(HERE/'source01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in plan['sources']:z.write(HERE/n,n)
        z.write(HERE/'plan01.json','plan01.json')
    sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
    remote='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/fixed_work_variance'
    w.ssh(f"if(Test-Path '{remote}'){{throw 'Existing fixed cohort'}};if(@(Get-Process python -ErrorAction SilentlyContinue).Count){{throw 'Existing targets'}};New-Item -ItemType Directory '{remote}'|Out-Null")
    w.transfer(HERE/'source01.zip',f'{w.HOST}:{remote}/source01.zip')
    print(w.ssh(f"if((Get-FileHash '{remote}/source01.zip').Hash.ToLower() -ne '{sha(HERE/'source01.zip')}'){{throw 'Package mismatch'}};& D:/conda/python.exe -m zipfile -e '{remote}/source01.zip' '{remote}';if($LASTEXITCODE){{throw 'Extract failed'}}"))
    print(json.dumps(dict(plan_sha256=sha(HERE/'plan01.json'),package_sha256=sha(HERE/'source01.zip'))))
