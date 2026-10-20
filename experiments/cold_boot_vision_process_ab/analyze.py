"""Analyze four reboot-separated first windows; no cross-boot replacement."""
import hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/session_gui_comparison'))
from metrics import measure
from decision import decide
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    plan=read(HERE/'plan02.json');stage=HERE/'runs/cold01';status=read(stage/'status.json');rows={};boots=[]
    original=Path(plan['input_root'])/'raw_frames.npz';assert sha(original)==plan['input_sha256']['raw_frames.npz']
    for case in plan['cases']:
        folder=stage/case['id'];record=read(folder/'record.json');assert record['complete'] and not record['errors'] and not record['target_still_running']
        value=measure(folder/'capture',original);boot=record['boot'];boots.append(boot['boot_100ns'])
        value.update(complete=True,vision_mode=case['vision_mode'],boot=boot,boot_qualified=plan['boot']['settle_seconds']<=boot['uptime_seconds']<=plan['boot']['maximum_uptime_seconds'] and boot['session_id']!=0 and boot['priority_class']==16384 and boot['ac_online']==1)
        rows[case['id']]=value
    assert len(set(boots))==len(boots)==4 and status['complete']
    result=dict(cases=rows,decision=decide(rows,plan),interpretation='Reboot-separated first-window saved-input crossover. Reboot is a compound state reset, not a named power/cache/frequency mechanism.',
        formal_program_modified=False,field_fix_verified=False,bindings=dict(plan_sha256=sha(HERE/'plan02.json'),analyzer_sha256=sha(Path(__file__))))
    (HERE/'result01.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
