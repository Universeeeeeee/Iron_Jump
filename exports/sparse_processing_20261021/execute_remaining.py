"""Finish and push each independent local experiment before starting the next."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def run(label,command):
    with (HERE/f'{label}.stdout').open('w') as out,(HERE/f'{label}.stderr').open('w') as err:
        result=subprocess.run([sys.executable,*command],cwd=ROOT,stdout=out,stderr=err)
    if result.returncode:raise RuntimeError((label,result.returncode))


def main():
    ledger=[]
    published=json.loads((HERE/'publish_ledger.json').read_text())
    assert any(r['experiment']=='E1' and r['pushed'] for r in published)
    for label,variant in (('E2a','runtime'),('E2b','idle'),('E3','clusters')):
        start=time.time()
        row={'experiment':label,'status':'correctness','started_unix':start};ledger.append(row)
        (HERE/'remaining_execution.json').write_text(json.dumps(ledger,indent=2))
        print('starting',label,'correctness',flush=True)
        pins={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in HERE.glob('*.py')}
        (HERE/f'{label}_tooling_manifest.json').write_text(json.dumps(pins,indent=2))
        run(label+'_checks',[str(HERE/'per_experiment_checks.py'),label,variant])
        run(label+'_regression',[str(HERE/'regression.py'),variant])
        row['status']='performance';(HERE/'remaining_execution.json').write_text(json.dumps(ledger,indent=2))
        print(label,'correctness and regression passed; scoring',flush=True)
        run(label,[str(HERE/'run_suite.py'),'one',label])
        assert all(hashlib.sha256((HERE/f).read_bytes()).hexdigest()==h for f,h in pins.items())
        row['status']='publishing';(HERE/'remaining_execution.json').write_text(json.dumps(ledger,indent=2))
        run('publish_'+label,[str(HERE/'finish_experiment.py'),label])
        row.update(status='pushed',elapsed_s=time.time()-start)
        (HERE/'remaining_execution.json').write_text(json.dumps(ledger,indent=2))
        print(label,'pushed',round(row['elapsed_s'],2),flush=True)
    run('publish_E4',[str(HERE/'finish_experiment.py'),'E4'])
    # Only independently admitted candidates may enter the combination.
    combined=[]
    for label in ('E1','E2a','E2b','E3'):
        combined.extend(json.loads((HERE/f'{label}_pipeline.json').read_text())['results'])
    (HERE/'pipeline_benchmarks.json').write_text(json.dumps({'results':combined,'complete':True},indent=2))
    print('starting gated combination',flush=True)
    run('combined',[str(HERE/'run_suite.py'),'combined'])
    if (HERE/'combined_features.json').exists():
        run('combined_regression',[str(HERE/'regression.py'),'combined'])
    print('all independent experiments pushed; combination finished',flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        import traceback
        traceback.print_exc();sys.exit(1)
