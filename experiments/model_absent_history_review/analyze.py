"""Reinspect all12 old model-absent chain replays; no workload launched."""
import ast
import hashlib
import json
from pathlib import Path
import statistics
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    old=ROOT/'experiments/walk_compute_offline_diagnosis';data=json.loads((old/'windows_chain01/chain.json').read_text())
    manifest=json.loads((old/'validation_manifest.json').read_text())['source_and_results_sha256']
    selected={k:v for k,v in manifest.items() if k in ('chain.py','replay.py','windows_chain01/chain.json')}
    assert len(selected)==3 and all(sha(old/n)==v for n,v in selected.items())
    assert data['script_sha256']==sha(old/'chain.py') and data['replay_script_sha256']==sha(old/'replay.py')
    # Record actual entrypoint call graph evidence, not a false dynamic module audit.
    imported=[]
    for name in ('chain.py','replay.py'):
        tree=ast.parse((old/name).read_text())
        imported.extend((node.module or '') for node in ast.walk(tree) if isinstance(node,ast.ImportFrom))
        imported.extend(alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names)
    assert not any('mediapipe' in n or n.startswith('vision') for n in imported)
    rows=[]
    for trial in data['trials']:
        assert len(trial['repeats'])==3
        for index,r in enumerate(trial['repeats']):
            assert r['report_and_quality_exact'];b=r['blocks'];formal=[v for v in b if v['block']>=0]
            rows.append(dict(case=trial['case'],repeat=index,preparation_wall_ms=b[0]['wall_ns']/1e6,
                formal_wall_ms=sum(v['wall_ns'] for v in formal)/1e6,formal_cpu_ms=sum(v['thread_cpu_ns'] for v in formal)/1e6,
                first_five_blocks=[dict(block=v['block'],wall_us_per_frame=v['wall_ns']/(v['raw_last']-v['raw_first']+1)/1e3,
                    cpu_us_per_frame=v['thread_cpu_ns']/(v['raw_last']-v['raw_first']+1)/1e3) for v in formal[:5]]))
    first=[r for r in rows if r['case']==data['trials'][0]['case']]
    out=dict(exploratory=True,all_twelve_replays_retained=True,entrypoint_imports=sorted(set(imported)),cases=rows,
        first_case_preparation_later_to_first_ratios=[v['preparation_wall_ms']/first[0]['preparation_wall_ms'] for v in first[1:]],
        interpretation='The old synchronous consumer-only entrypoint invokes no model creation/inference. Repeated identical inputs show timing variation even in this fixture. This constrains active in-process MediaPipe inference as a necessary explanation; it does not prove the same latent state as current GUI or rule out external workload.',
        limitations=['No dynamic process-wide module/thread inventory was saved; entrypoint/source evidence is narrower than proof of no external MediaPipe process.',
            'Old input/fixture differs from current6824-frame bundle. Do not transfer joint state labels orsubtract timings across protocols.',
            'No current hardware delivery, trigger, thermal limit orGIL share is identified.'],
        root_mechanism_identified=False,
        bindings={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__),old/'chain.py',old/'replay.py',old/'windows_chain01/chain.json',old/'validation_manifest.json')})
    with (HERE/'result01.json').open('x') as f:json.dump(out,f,indent=2)
    print('Verified12 historical chain replays; first-case prep later/first:',out['first_case_preparation_later_to_first_ratios'])
