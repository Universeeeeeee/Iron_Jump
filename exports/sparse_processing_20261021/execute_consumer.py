"""Use consumer-only CPU results for decisions; publish each completed experiment."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def run(label,script,*args):
    with (HERE/(label+'.stdout')).open('w') as out,(HERE/(label+'.stderr')).open('w') as err:
        r=subprocess.run([sys.executable,str(HERE/script),*args],cwd=ROOT,stdout=out,stderr=err)
    if r.returncode:raise RuntimeError((label,r.returncode))


def publish_consumer(label):
    result=json.loads((HERE/f'{label}_consumer.json').read_text())
    assert result['complete']
    path=HERE/f'{label}_pipeline.json'
    old=json.loads(path.read_text()) if path.exists() else {}
    if path.exists() and old.get('scope')!='consumer_only':
        shutil.copy2(path,HERE/f'{label}_serial_pipeline.json')
    variants=sorted({r['variant'] for r in result['results']})
    (HERE/f'{label}_pipeline.json').write_text(json.dumps({'results':result['results'],'complete':True,
        'selected_variants':variants,'scope':'consumer_only',
        'segmented_decoder_beats_simple_cache':old.get('segmented_decoder_beats_simple_cache')},indent=2))
    run('publish_'+label+'_consumer','finish_experiment.py',label)


def main():
    ledger=[]
    for label,variant in (('E1','decode_full'),('E2a','runtime'),('E2b','idle'),('E3','clusters')):
        start=time.time();row={'experiment':label,'status':'running','role':'consumer_only'};ledger.append(row)
        (HERE/'consumer_execution.json').write_text(json.dumps(ledger,indent=2))
        pins={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in HERE.glob('*.py')}
        (HERE/f'{label}_consumer_tooling.json').write_text(json.dumps(pins,indent=2))
        print('starting',label,'consumer-specific experiment',flush=True)
        if label in ('E2b','E3'):
            run(label+'_checks_final','per_experiment_checks.py',label,variant)
            run(label+'_regression_final','regression.py',variant)
            # Measure only the isolated stage here; the full-chain comparator is
            # consumer_bench, rather than the superseded serial pipeline loop.
            target='formal_processor' if label=='E2b' else 'formal_clusters'
            code='''import sys,json
sys.path.insert(0,sys.argv[1])
from run_suite import paired
from experiment import HERE,dump
rows=[]
for case in ('empty','sparse','cross','plateau','stress','field_run_20261015_02','field_walk_full_02'):
 rows.append(paired(case,sys.argv[3],sys.argv[4]));dump(HERE/(sys.argv[2]+'_stage.json'),{'results':rows,'complete':False})
dump(HERE/(sys.argv[2]+'_stage.json'),{'results':rows,'complete':True})
'''
            with (HERE/f'{label}_stage.stdout').open('w') as out,(HERE/f'{label}_stage.stderr').open('w') as err:
                r=subprocess.run([sys.executable,'-c',code,str(HERE),label,variant,target],cwd=ROOT,stdout=out,stderr=err)
            if r.returncode:raise RuntimeError((label,'stage',r.returncode))
        run(label+'_consumer','consumer_bench.py',label,variant)
        assert all(hashlib.sha256((HERE/f).read_bytes()).hexdigest()==h for f,h in pins.items())
        publish_consumer(label)
        row.update(status='pushed',elapsed_s=time.time()-start)
        (HERE/'consumer_execution.json').write_text(json.dumps(ledger,indent=2))
        print(label,'consumer-specific result pushed',round(row['elapsed_s'],2),flush=True)
    run('publish_E4','finish_experiment.py','E4')
    features=[]
    for label in ('E2a','E2b','E3'):
        d=json.loads((HERE/f'{label}_consumer.json').read_text())
        if d['consumer_cpu_gate']:features.append(d['results'][0]['variant'])
    # Reader cache is admitted by its separate reader-stage gate, not by
    # attributing decoder CPU to the consumer thread.
    e1=json.loads((HERE/'E1_decision.json').read_text())
    if e1['reader_decoder_gate']:features.append('decode_full')
    (HERE/'combined_features.json').write_text(json.dumps({'selected':features,
        'scope':'consumer candidates admitted on consumer-only gate; decode_full on separate reader gate'},indent=2))
    if not features:return
    import os
    os.environ['IRON_SPARSE_FEATURES']=','.join(features)
    run('combined_checks','per_experiment_checks.py','combined','combined')
    run('combined_regression_final','regression.py','combined')
    run('combined_consumer','consumer_bench.py','combined','combined')
    print('gated combination complete',flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        import traceback
        traceback.print_exc();sys.exit(1)
