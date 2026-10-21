"""Windows CPU-only cross-check; no UsbWorker, camera or SDK is constructed."""
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
LAB=HERE.parent


def main():
    label,variant=sys.argv[1:3]
    if ',' in variant:
        os.environ['IRON_SPARSE_FEATURES']=variant
        variant='combined'
    rows=[]
    folder=LAB/'benchmarks';folder.mkdir(exist_ok=True)
    for case in ('empty','sparse','cross','plateau','stress',
                 'field_run_20261015_02','field_walk_full_02'):
        pairs=[]
        for pair,order in enumerate((('baseline',variant),(variant,'baseline'),
                                     ('baseline',variant),(variant,'baseline'))):
            results={}
            for n,name in enumerate(order):
                path=folder/f'{label}_{case}_{pair}_{n}_{name}.json'
                cmd=[sys.executable,str(LAB/'experiment.py'),'bench','--case',case,
                     '--variant',name,'--target','pipeline','--output',str(path)]
                with path.with_suffix('.stdout').open('w') as out,path.with_suffix('.stderr').open('w') as err:
                    subprocess.run(cmd,stdout=out,stderr=err,check=True)
                results[name]=json.loads(path.read_text())
            a,b=results['baseline'],results[variant]
            assert a['report_sha256']==b['report_sha256'],(case,pair,'report')
            pairs.append({'pair':pair,'order':order,'baseline':a,'candidate':b,
                          'cpu_reduction':1-b['cpu_ns']/a['cpu_ns']})
        reductions=[p['cpu_reduction'] for p in pairs]
        rows.append({'case':case,'variant':variant,'pairs':pairs,
                     'median_cpu_reduction':statistics.median(reductions),
                     'positive_pairs':sum(x>0 for x in reductions)})
        (LAB/(label+'.native.json')).write_text(json.dumps({'complete':False,'results':rows},indent=2))
        print(case,round(statistics.median(reductions)*100,2),flush=True)
    pins=json.loads((LAB/'native_preflight.json').read_text())['formal_plan16_hashes']
    root=LAB.parents[1]
    plan=json.loads((root/'experiments/live_consumer_process_candidate16/plan16.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==v for n,v in plan['formal_sha256'].items())
    result={'complete':True,'results':rows,'platform':platform.platform(),'python':sys.version,
            'formal_sources_unchanged':True,'scope':'Windows original NumPy, CPU-only unpaced pipeline. No GUI, process+batch40 transport, camera, SDK, ETW or physical acquisition. No FIFO/contact-to-paint conclusion.'}
    (LAB/(label+'.native.json')).write_text(json.dumps(result,indent=2))
    print('complete',label,flush=True)


if __name__=='__main__':main()
