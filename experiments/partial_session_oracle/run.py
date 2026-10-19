"""Four existing windows only, full normal positive control first. No capture."""
import hashlib
import json
from pathlib import Path
import sys
from recompute import recompute
from compare import differences

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=read(HERE/'plan01.json');gate=read(HERE/'preflight_passed01.json')
    assert gate['passed'] and gate['plan_sha256']==sha(HERE/'plan01.json') and gate['tests_sha256']==sha(HERE/'windows_tests01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    assert all(sha(ROOT/n)==v for n,v in plan['evidence_files'].items())
    sys.path.insert(0,str(ROOT))
    from qtpy.QtCore import QCoreApplication
    app=QCoreApplication.instance() or QCoreApplication([])
    stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir();result=dict(complete=False,cases=[],errors=[],new_capture=False)
    try:
        for case in plan['cases']:
            folder=stage/case['name'];folder.mkdir();(folder/'active.lock').mkdir()
            target=ROOT/case['actor_folder']
            report,state,bounds=recompute(plan['input_root'],target,plan['checked_sample'],case['reason'])
            for name,value in [('recomputed_report.json',report),('recomputed_state.json',state)]:
                with (folder/name).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False)
            report_diff=differences(report,read(target/'report.json'));state_diff=differences(state,read(target/'state.json'))
            row=dict(name=case['name'],bounds=bounds,report_exact=not report_diff,state_exact=not state_diff,report_mismatches=report_diff,state_mismatches=state_diff,
                recomputed_report_sha256=sha(folder/'recomputed_report.json'),recomputed_state_sha256=sha(folder/'recomputed_state.json'))
            with (folder/'result.json').open('x') as f:json.dump(row,f,indent=2)
            result['cases'].append(row);print(json.dumps(row),flush=True)
            if report_diff or state_diff:raise ValueError('Original replay mismatch retained: '+case['name'])
        result['complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(result,f,indent=2)
    raise SystemExit(not result['complete'])
