"""Apply the existing recovery correction to a new frozen-rate synthetic control."""
import argparse
import json
from pathlib import Path
from control import read,sha,write
import verify_recovery02


def cadence(rows,plan,tid):
    init=rows[0];samples=[s for s in rows if s['kind']=='sample'];f=init['qpc_frequency']
    gaps=[(b['qpc_begin']-a['qpc_begin'])*1000/f for a,b in zip(samples,samples[1:])]
    return dict(requested=init['period_ms']==plan['period_ms'] and init['requested_count']==plan['count_per_phase'] and init['requested_tid']==tid,
                actual_gap_ms=gaps,within_pacing_budget=len(samples)==plan['count_per_phase'] and all(plan['period_ms']-1<=g<=plan['period_ms']+50 for g in gaps))


def main(a):
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items())
    plan=read(a.raw/'plan01.json');record=read(a.raw/'run01/record.json');resolved=read(a.raw/'symbols01.json')
    assert record['plan_sha256']==sha(a.raw/'plan01.json') and all(sha(a.raw/n)==h for n,h in plan['sources'].items())
    assert all(sha(Path(__file__).parent/n)==plan['sources'][n] for n in ('verify.py','verify_recovery02.py','control.py'))
    assert sha(a.raw/'WaiterOracle.dll')==plan['oracle_dll_sha256']
    assert sha(a.raw/'target/release/ironjump-gil-waiter-control.exe')==plan['observer_sha256']
    assert b''.join((a.raw/f'run01/phase{i}/samples.jsonl').read_bytes() for i in (1,2))==(a.raw/'all_samples.jsonl').read_bytes()
    assert resolved['samples_sha256']==sha(a.raw/'all_samples.jsonl') and resolved['resolver_sha256']==plan['sources']['resolve_raw.py'] and resolved['dbghelp_sha256']==plan['dbghelp_sha256']
    assert not (a.raw/'run01/target.log').read_bytes() and all(not (a.raw/f'run01/phase{i}/observer.log').read_bytes() for i in (1,2))
    streams={str(i):[json.loads(l) for l in (a.raw/f'run01/phase{i}/samples.jsonl').read_text().splitlines()] for i in (1,2)}
    result=verify_recovery02.inspect(record,streams,plan,resolved,a.root)
    result['cadence']={k:cadence(rows,plan,record['ready']['tids']['waiter']) for k,rows in streams.items()}
    result['checks']['proposed_rate_delivered']=all(v['requested'] and v['within_pacing_budget'] for v in result['cadence'].values())
    result['deterministic_waiter_control_pass']=all(result['checks'].values())
    result['evidence']=dict(plan_sha256=sha(a.raw/'plan01.json'),manifest_sha256=sha(a.raw/'manifest.json'),reviewer_sha256=sha(Path(__file__)))
    result['scope']='New4Hz/count20 synthetic control only; no resampling of prior failures, no actual-load or field quantitative qualification.'
    write(a.output,result)
    print({k:v for k,v in result.items() if k not in ('joins','phase_checks')})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
