"""Explain the retained failed requirement without changing its frozen result."""
import argparse
import json
from pathlib import Path
from verify import read,sha


def inspect(rows,resolved,result):
    samples={s['ordinal']:s for s in rows if s['kind']=='sample'}
    addresses={a['address']:a for m in resolved['modules'] for a in m['resolved']}
    details=[]
    for join in result['joins']:
        if join['matches']:continue
        s=samples[join['ordinal']];owner=[t for t in s['traces'] if t['owns_gil']]
        assert len(owner)==1
        waiting=[n for n in s['native'] if n['tid']!=owner[0]['os_thread_id']];assert len(waiting)==1
        frames=[addresses[a['address']] for a in waiting[0]['frames']];names=[a['symbol'] for a in frames]
        names_proven=all(a['pdb_matched'] for a in frames if a['symbol'] in ('pysleep','NtWaitForSingleObject','BaseThreadInitThunk','RtlUserThreadStart'))
        native_sleep=names_proven and all(n in names for n in ('pysleep','NtWaitForSingleObject')) and names[-2:]==['BaseThreadInitThunk','RtlUserThreadStart'] and 'take_gil' not in names and 'PyEval_RestoreThread' not in names
        other_requirements=all(join[k] for k in ('owner_and_python_frame','raw_contexts','both_roots_closed','owner_path','external_oracle_agrees'))
        details.append(dict(ordinal=join['ordinal'],requested_tid=waiting[0]['tid'],phase=join['phase'],closed_native_sleep=native_sleep,other_identity_and_native_checks_pass=other_requirements,proven_native_symbols=names))
    explained=bool(details) and all(d['closed_native_sleep'] and d['other_identity_and_native_checks_pass'] for d in details)
    return dict(frozen_dynamic_control_pass=result['dynamic_synthetic_control_pass'],failed_requirement='every_eligible_matches: requested waiter must have take_gil + PyEval_RestoreThread in every eligible sample',eligible_owner_frame_matches=sum(j['owner_and_python_frame'] for j in result['joins']),eligible_count=len(result['joins']),unknown=result['unknown'],failed_waiter_count=len(details),failed_waiter_samples=details,all_failed_samples_explained_as_sleep_without_GIL_acquisition=explained,all_pause_probes_and_running_controls_pass=result['checks']['inner_native_heartbeat_still'] and result['checks']['running_negative_controls'],field_attribution_ready=False,scope='Derived explanation of the same failed window, not a new acceptance or replacement capture. A Python thread in time.sleep may still be sleeping instead of reacquiring GIL; do not infer time shares from these observations.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--result',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    rows=[json.loads(l) for l in (a.raw/'run01/samples.jsonl').read_text().splitlines()];v=inspect(rows,read(a.raw/'resolved01.json'),read(a.result))
    v.update(samples_sha256=sha(a.raw/'run01/samples.jsonl'),frozen_result_sha256=sha(a.result),reviewer_sha256=sha(Path(__file__)))
    with a.output.open('x') as f:json.dump(v,f,indent=2)
    print(json.dumps({k:v for k,v in v.items() if k!='failed_waiter_samples'},indent=2))
