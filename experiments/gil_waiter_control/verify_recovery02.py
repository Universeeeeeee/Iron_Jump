"""Offline recovery-boundary correction; never edits frozen sources/results or captures."""
import argparse
import json
from pathlib import Path
import verify
from control import read,sha


def recovered(record):
    end=max(g['external_end_ns'] for g in record['phases'].values())
    during=[p for p in record['oracle'] if p[1]<=end]
    return bool(during) and record['complete']['completed'] and record['complete']['pid']==record['ready']['pid'] and record['complete']['acquired']==2 and record['complete']['host_ns']>end and record['complete']['heartbeat']>max(p[5] for p in during) and all(g['done']['acquired']==int(k) and g['done']['host_ns']>g['external_end_ns'] for k,g in record['phases'].items())


def inspect(record,streams,plan,resolved,root):
    result=verify.inspect(record,streams,plan,resolved,root)
    original=result['checks']['recovered'];result['checks']['recovered']=recovered(record)
    result['deterministic_waiter_control_pass']=all(result['checks'].values())
    result['recovery_boundary_correction']=dict(original_recovered=original,corrected_recovered=result['checks']['recovered'],reason='The native heartbeat stops before complete.json. Multiple post-stop oracle reads may equal complete. Compare against externally bracketed capture-window observations, require complete after the window and both native acquired markers after owner release. All other frozen checks remain unchanged; no resampling.')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    here=Path(__file__).resolve().parent;review=read(here/'review02_plan.json')
    assert all(sha(here/n)==h for n,h in review['sources'].items()) and sha(a.raw/'manifest.json')==review['raw_manifest_sha256'] and sha(here/'result01.json')==review['original_result_sha256']
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items());plan=read(a.raw/'plan01.json');record=read(a.raw/'run01/record.json')
    streams={str(i):[json.loads(l) for l in (a.raw/f'run01/phase{i}/samples.jsonl').read_text().splitlines()] for i in (1,2)};resolved=read(a.raw/'symbols01.json')
    assert verify.inspect(record,streams,plan,resolved,a.root)==read(here/'result01.json')
    result=inspect(record,streams,plan,resolved,a.root)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('joins','phase_checks')},indent=2))
