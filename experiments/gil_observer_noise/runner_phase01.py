"""Fixed independent A/A or observer pairs, no adaptive success chasing."""
import argparse
from pathlib import Path
import sys
import control_phase01 as original
from control03 import read,sha,write


def main(a):
    plan=read(a.plan);a.output.mkdir(exist_ok=False);lock=a.output.parent/'active.lock';lock.mkdir();result=dict(errors=[],cases={},actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:
        def unchanged():return sha(a.tool)==plan['observer_sha256'] and all(sha(a.plan.parent/n)==h for n,h in plan['sources'].items())
        assert unchanged() and sha(Path(sys.base_prefix)/'python311.dll')==plan['python_dll_sha256']
        assert sha(Path(plan['replay_root'])/'experiments/walk_compute_offline_diagnosis/replay.py')==plan['replay_helper_sha256']
        sys.path.insert(0,plan['native_helpers'])
        for spec in plan['cases']:
            assert spec['mode'] in ('off','on')
            case=original.case(spec['mode'],a.output/spec['id'],plan,a)
            result['cases'][spec['id']]=dict(case_pass=case['case_pass'],mode=spec['mode'])
            assert case['case_pass'],'Invalid measurement case: retain and abort, never replace'
        assert unchanged();result['capture_protocol_complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        result['plan_sha256']=sha(a.plan);result['lock_retained']=lock.is_dir();write(a.output/'result.json',result)
    return int(bool(result['errors']))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--tool',type=Path,required=True);p.add_argument('--output',type=Path,required=True);raise SystemExit(main(p.parse_args()))
