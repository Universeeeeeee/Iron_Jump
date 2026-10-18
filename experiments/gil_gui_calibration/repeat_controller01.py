"""User-authorized independent repeat; reuse the exact earlier GUI case function."""
import json
from pathlib import Path
import sys
from aa_controller01 import case,read,sha
from atomic_io03 import write


HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]


def main():
    plan=read(HERE/'repeat_plan01.json');stage=HERE/'runs/restart_repeat01';stage.mkdir(parents=True,exist_ok=False);lock=stage/'active.lock';lock.mkdir()
    result=dict(errors=[],cases=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:
        frozen=read(HERE/'repeat_frozen01.json')['files']
        def unchanged():return all(sha(ROOT/n)==h for n,h in frozen.items()) and all(sha(ROOT/n)==h for n,h in plan['baseline_files'].items())
        assert unchanged();sys.path.insert(0,str(HERE))
        for name in plan['cases']:
            case(name,stage,plan);result['cases'].append(name);assert unchanged()
        result['all_fixed_cases_complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        result['plan_sha256']=sha(HERE/'repeat_plan01.json');result['lock_retained']=lock.is_dir();write(stage/'result01.json',result)
    print(json.dumps(result),flush=True);return int(bool(result['errors']))


if __name__=='__main__':raise SystemExit(main())
