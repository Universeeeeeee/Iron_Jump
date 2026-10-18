"""Continue only the unexecuted cases after a retained analysis-deployment failure."""
import argparse
import json
from pathlib import Path
import sys
import control
from control import read,sha,write


def main(a):
    plan=read(a.plan);here=a.plan.parent;fix=read(here/'completion02_plan.json');record=dict(errors=[],pairs=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    a.output.mkdir(exist_ok=False)
    try:
        assert sha(a.plan)==fix['original_plan_sha256'] and all(sha(here/n)==h for n,h in fix['sources'].items()) and all(sha(here/n)==h for n,h in plan['sources'].items()) and sha(a.tool)==plan['observer_sha256']
        assert sha(a.cases/'result.json')==fix['original_failure_result_sha256'] and read(a.cases/'result.json')['errors']==['ModuleNotFoundError("No module named \'align_clock\'")']
        assert (here/'active.lock').is_dir()
        sys.path.insert(0,plan['native_helpers']);import align_clock
        assert sha(Path(align_clock.__file__))==fix['sources']['align_clock.py']
        first=a.cases/'pair1_off'
        old_record=read(first/'record.json');assert not old_record['errors'] and old_record['target_returncode']==0
        recovered=control.case_result(old_record,read(first/'target/roi.json'),read(first/'target/complete.json'),[],plan,Path(plan['replay_root']))
        write(a.output/'recovered_pair1_off_analysis.json',recovered)
        for i,order in enumerate(plan['orders'],1):
            cases={}
            for mode in order:
                if i==1 and mode=='off':cases[mode]=recovered
                else:
                    folder=a.cases/f'pair{i}_{mode}';assert not folder.exists(),'Never repeat an executed case'
                    cases[mode]=control.case(mode,folder,plan,a)
            paired=control.pair_result(cases['off'],cases['on'],plan);record['pairs'].append(dict(pair=i,**paired));print(json.dumps(record['pairs'][-1]),flush=True)
        assert all(sha(here/n)==h for n,h in plan['sources'].items()) and all(sha(here/n)==h for n,h in fix['sources'].items())
        record['offline_contact_chain_perturbation_pass']=all(p['offline_contact_chain_pair_pass'] for p in record['pairs'])
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        record.update(original_plan_sha256=sha(a.plan),completion_plan_sha256=sha(here/'completion02_plan.json'),original_failure_retained=True,first_off_not_repeated=True,lock_retained=(here/'active.lock').is_dir());write(a.output/'result.json',record)
    return int(bool(record['errors']) or not record.get('offline_contact_chain_perturbation_pass',False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--tool',type=Path,required=True);p.add_argument('--cases',type=Path,required=True);p.add_argument('--output',type=Path,required=True);raise SystemExit(main(p.parse_args()))
