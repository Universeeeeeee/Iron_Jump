"""Calibrate the offline adapter, then compare four pairs without physical input."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def normalised(folder):
    actor=folder/'client/actor'
    report=json.loads((actor/'report.json').read_text())
    state=json.loads((actor/'state.json').read_text())
    for branch in (report['report_config_snapshot']['device'],
                   report['report_config_snapshot']['beam_quality']['preflight'],
                   state['quality']['preflight']):
        assert isinstance(branch['checked_monotonic_ns'],int)
        del branch['checked_monotonic_ns']
    return report,state


def first_diff(a,b,path=''):
    if type(a)!=type(b):return path+':type'
    if isinstance(a,dict):
        if a.keys()!=b.keys():return path+':keys'
        for key in a:
            value=first_diff(a[key],b[key],path+'/'+str(key))
            if value:return value
    elif isinstance(a,list):
        if len(a)!=len(b):return path+':length'
        for n,(x,y) in enumerate(zip(a,b)):
            value=first_diff(x,y,path+'/'+str(n))
            if value:return value
    elif a!=b:return path+':'+repr(a)[:80]+'!='+repr(b)[:80]


def main():
    lab=Path(os.environ['IRON_SPARSE_LAB'])
    features=sys.argv[1]
    assert features and set(features.split(','))<= {'runtime','idle','clusters'}
    plan=json.loads((ROOT/'experiments/live_consumer_process_candidate16/plan16.json').read_text(encoding='utf-8'))
    fixture=Path(plan['fixture_root'])
    for name,sha in plan['fixture_sha256'].items():
        assert hashlib.sha256((fixture/name).read_bytes()).hexdigest()==sha,('fixture',name)
    source_pins=json.loads((lab/'manifest.json').read_text())['production_sources']
    paths=set(plan['formal_sha256'])|{'ui/footprint_channel.py','hardware/sensor_frame.py',
                                    'hardware/walking_preflight.py','hardware/payload_mirror.py'}
    def verify():
        for name in paths:
            assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==source_pins[name],('production source',name)
    verify()
    runs=HERE/'runs';runs.mkdir(exist_ok=False)
    ledger=[];reference=None;reference_sha=None
    def run(name,variant):
        nonlocal reference,reference_sha
        out=runs/name
        env=dict(os.environ,QT_QPA_PLATFORM='offscreen',PYTHONUNBUFFERED='1')
        command=[sys.executable,str(HERE/'offline_gui.py'),'--fixture',str(fixture),
                 '--output',str(out),'--variant',variant,'--features',features]
        with (runs/(name+'.stdout')).open('w') as stdout,(runs/(name+'.stderr')).open('w') as stderr:
            result=subprocess.run(command,env=env,stdout=stdout,stderr=stderr,timeout=180)
        record=json.loads((out/'offline_result.json').read_text()) if (out/'offline_result.json').exists() else {'complete':False}
        record.update(name=name,variant=variant,returncode=result.returncode)
        ledger.append(record)
        (HERE/'gui_progress.json').write_text(json.dumps(ledger,indent=2))
        assert result.returncode==0 and record['complete'],(name,result.returncode,record)
        current=normalised(out)
        if reference is None:reference=current;reference_sha=record['raw_sha256']
        difference=first_diff(reference,current)
        assert difference is None,(name,'SEMANTIC DIFFERENCE',difference)
        assert record['raw_sha256']==reference_sha,(name,'raw input difference')
        record['full_report_quality_runtime_events_timeline_exact']=True
        record['semantic_sha256']=hashlib.sha256(canonical(current).encode()).hexdigest()
        (HERE/'gui_progress.json').write_text(json.dumps(ledger,indent=2))
        print(name,'complete','upper',record['unfinished_upper_bound'],
              'p95',record['p95_contact_to_paint_ms'],flush=True)
        return record
    # These two runs calibrate fixed arming, video activity and exact semantics.
    # They are retained separately and never pooled with scored pairs.
    run('calibration_baseline','baseline')
    run('calibration_candidate','combined')
    pairs=[]
    for n,order in enumerate((('baseline','combined'),('combined','baseline'),
                              ('baseline','combined'),('combined','baseline'))):
        values={variant:run(f'pair{n}_{index}_{variant}',variant) for index,variant in enumerate(order)}
        a,b=values['baseline'],values['combined']
        assert abs(a['video']['decoded_frames']-b['video']['decoded_frames'])<=.05*max(1,a['video']['decoded_frames']),('video load mismatch',n)
        pairs.append({'pair':n,'order':order,'baseline':a,'candidate':b,
            'latency_reduction':1-b['p95_contact_to_paint_ms']/a['p95_contact_to_paint_ms']})
        (HERE/'gui_pairs.json').write_text(json.dumps({'complete':False,'pairs':pairs},indent=2))
    verify()
    changes=[p['latency_reduction'] for p in pairs]
    result={'complete':True,'pairs':pairs,'features':features.split(','),
            'all_semantics_exact':True,'physical_hardware_started':False,
            'all_candidate_performance_gates':all(p['candidate']['performance_pass'] for p in pairs),
            'stable_latency_improvement':sum(x>0 for x in changes)>=3 and statistics.median(changes)>=.20,
            'median_latency_reduction':statistics.median(changes),
            'production_source_hashes_unchanged':True,
            'scope':'Windows offscreen ExecutionView + saved JPEG replay + original consumer process/batch40 transport. No hardware, SDK/pose load, actual display presentation or human gait acceptance.'}
    (HERE/'gui_pairs.json').write_text(json.dumps(result,indent=2))
    print('complete matrix',json.dumps({k:v for k,v in result.items() if k!='pairs'}),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        import traceback
        traceback.print_exc();sys.exit(1)
