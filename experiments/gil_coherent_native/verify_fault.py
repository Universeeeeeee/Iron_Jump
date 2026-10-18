"""Check a failed synthetic capture stayed failed and its target recovered."""
import argparse
import hashlib
import json
from pathlib import Path


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def inspect(record,rows,post,log):
    held=[p for p in record['oracle'] if p[2]==p[6] and p[2]%2==0 and p[3]==1]
    checks=dict(explicit_read_error=len(rows)==2 and rows[0]['kind']=='init' and rows[0]['error'] is None and rows[1]['kind']=='error' and rows[1]['error']=='Requested/owner OS thread missing' and rows[1]['ordinal']==0,
        no_false_complete=not record.get('capture_complete',False) and bool(record['errors']) and all(r['kind'] not in ('sample','complete') for r in rows),
        observer_failed_with_log=record['observer_returncode']==1 and 'Requested/owner OS thread missing' in log,
        target_terminal_recovered=record['target_returncode']==0 and not record['target_still_running'] and not record['observer_still_running'] and record['complete']['completed'] and bool(held) and record['complete']['heartbeat']>max(p[5] for p in held),
        native_handle_lifetimes=all(a['active'] and b['active'] and a['creation_100ns']==b['creation_100ns'] for a,b in zip(record['before'],record['after'])),
        locks_preserved=post['fault_lock_retained'] and post['old_field_fault_lock_retained'] and post['old_failed_marker_lock_retained'],
        sources_unchanged=all(post[k] for k in ('constant_plan_sources_unchanged','fault_plan_sources_unchanged','formal_458_unchanged','old_field_sources_unchanged')),
        machine_interval_unchanged=post['sample_interval_100ns']==10000)
    return dict(checks=checks,fault_recovery_control_pass=all(checks.values()),capture_success=False,fault_lock_retained=True,field_attribution_ready=False,scope='A distinct intentional failed capture. Recovery shows the synthetic process was not left suspended; error row, stderr and lock are retained. No field owner or CPU/GIL contribution is inferred.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--constant-raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items());plan=read(a.raw/'fault_plan01.json');record=read(a.raw/'fault01/run01/record.json')
    assert sha(a.raw/'fault_plan01.json')==record['plan_sha256'] and all(sha((a.raw if (a.raw/n).exists() else a.constant_raw)/n)==h for n,h in plan['sources'].items())
    rows=[json.loads(s) for s in (a.raw/'fault01/run01/samples.jsonl').read_text().splitlines()]
    result=inspect(record,rows,read(a.raw/'post_fault01.json'),(a.raw/'fault01/run01/observer.log').read_text())
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
