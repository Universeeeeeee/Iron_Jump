"""Read-only review of the user-limited two reboot-separated windows."""
import hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/session_gui_comparison'))
from metrics import measure
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    plan=read(HERE/'plan03.json');source=Path(plan['retained_window_path']);manifest=read(HERE/plan['retained_manifest_file'])
    assert sha(HERE/plan['retained_manifest_file'])==plan['retained_manifest_sha256'] and all(sha(source/name)==digest for name,digest in manifest['files'].items())
    original=Path(plan['input_root'])/'raw_frames.npz';assert sha(original)==plan['input_sha256']['raw_frames.npz']
    rows={};boots=[]
    for name in plan['review_cases']:
        folder=source/'runs/cold01'/name;record=read(folder/'record.json');assert record['complete'] and not record['errors'] and not record['target_still_running']
        value=measure(folder/'capture',original);value['boot']=record['boot'];value['vision_mode']=record['case']['vision_mode'];boots.append(record['boot']['boot_100ns']);rows[name]=value
    assert len(set(boots))==2
    process=rows['cold01_process'];original_row=rows['cold02_original'];g=plan['decision']
    process_severe=process['observed_queue_lower']>=g['severe_queue_lower'] and process['scheduled_max_ms']>=g['severe_latency_ms']
    process_bounded=process['queue_upper']<=g['process_queue_upper'] and process['scheduled_max_ms']<=g['process_latency_ms']
    original_severe=original_row['observed_queue_lower']>=g['severe_queue_lower'] and original_row['scheduled_max_ms']>=g['severe_latency_ms']
    if process_severe:conclusion='Process isolation is not sufficient to prevent a severe cold-first backlog.'
    elif process_bounded and original_severe:conclusion='Direction supports the process candidate, but one process-first/original-second order cannot establish causality.'
    elif process_bounded:conclusion='The process-first window was bounded, but the following original window was not severe; severe-state benefit remains untested.'
    else:conclusion='The two-window result is descriptive and does not meet either severe or bounded decision pattern.'
    result=dict(cases=rows,process_first_severe=process_severe,process_first_bounded=process_bounded,original_second_severe=original_severe,
        conclusion=conclusion,original_four_window_crossover_completed=False,user_limited_to_two_reboots=True,
        root_function_identified=False,formal_fix_verified=False,field_fix_verified=False,
        bindings=dict(retained_manifest_sha256=plan['retained_manifest_sha256'],retained_archive_sha256=plan['retained_archive_sha256'],retained_plan_sha256=plan['retained_plan_sha256'],review_sha256=sha(Path(__file__))))
    (HERE/'result_two03.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
