"""Analyze every frozen A/A and original/process window without post-hoc subsets."""
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/session_gui_comparison'))
from metrics import measure
from decision import decide
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def signature(context):
    return dict(policy=context['policy'],foreground_gui=context['foreground_gui'])

if __name__=='__main__':
    plan=read(HERE/'plan02.json');stage=HERE/'runs/cohort01';status=read(stage/'status.json');rows={}
    original=ROOT/'experiments/session_isolation_throughput/runs/recorded_source01.npz';assert sha(original)==plan['input_sha256']['raw_frames.npz']
    for case in plan['cases']:
        folder=stage/case['id'];record=folder/'record.json'
        if not record.exists():rows[case['id']]=dict(complete=False,not_attempted=True);continue
        retained=read(record)
        if not retained.get('complete') or retained['errors'] or retained['target_still_running']:
            rows[case['id']]=dict(complete=False,failed=True,record=retained);continue
        value=measure(folder/'capture',original);value.update(complete=True,vision_mode=case['vision_mode'],case=case,context_comparable=True)
        rows[case['id']]=value
    for pair in plan['pairs']:
        a,b=rows[pair['original']],rows[pair['process']]
        if a.get('complete') and b.get('complete'):
            matched=signature(a['context'])==signature(b['context']);a['context_comparable']=b['context_comparable']=matched
    complete=status['complete'] and not status['errors'] and all(v.get('complete') for v in rows.values())
    outcome=decide(rows,plan) if complete else dict(advance=False,reason='incomplete_or_failed_window',field_fix_verified=False)
    result=dict(cases=rows,cohort_complete=complete,decision=outcome,
        interpretation='Timed original LiveWalkingVision versus the same implementation owning decode/model in a child. Whole boundary includes IPC and scheduler effects; no exclusive GIL or CPU share.',
        old_3pct_1pct_observer_gate_upgraded=False,formal_program_modified=False,field_fix_verified=False,
        limits=['All 12 frozen windows retained; no replacement or extension.','A/A range gate is required for quantitative attribution; descriptive pairs do not override its failure.',
            'Dynamic frame/model selections remain outcomes and are never posthoc equalized.','Saved input and real SDK are not a live USB/camera field fix.'],
        bindings=dict(plan_sha256=sha(HERE/'plan02.json'),analyzer_sha256=sha(Path(__file__))))
    with (HERE/'result01.json').open('x') as target:json.dump(result,target,indent=2)
    print(json.dumps(dict(complete=complete,decision=outcome,cases={name:{k:value.get(k) for k in ('vision_mode','scheduled_max_ms','observed_queue_lower','queue_upper','input_lateness_ms','complete','failed','not_attempted')} for name,value in rows.items()}),indent=2))
