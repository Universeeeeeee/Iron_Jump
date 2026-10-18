"""Verify direct stdin evidence independently from runtime pose_input counts."""
import hashlib
import json
from pathlib import Path

read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def inspect(cases):
    checks={};summary={}
    for mode,r in cases.items():
        sent=[x for x in r['input_sent'] if 'pose_packet' in x['value']];raw=[x for x in r['raw_line_reads'] if 'pose_packet' in json.loads(x['line'])];logs=[x for x in r['original_replies'] if x['value'].get('tracking_log',{}).get('event')=='pose_input']
        checks[mode+'_complete']=r['returncode']==0 and not r['serve_thread_alive'] and not r['errors'] and r['fake_sdk_calls'][-1]['kind']=='control_closed'
        checks[mode+'_wire_reader_identity']=len(r['raw_line_reads'])==len(r['input_sent']) and [x['sequence'] for x in r['raw_line_reads']]==list(range(1,len(r['input_sent'])+1)) and all(json.loads(a['line'])==b['value'] for a,b in zip(r['raw_line_reads'],r['input_sent']))
        checks[mode+'_sdk_owner']=len({x['tid'] for x in r['fake_sdk_calls']})==1 and {x['tid'] for x in r['fake_sdk_calls']}.isdisjoint({x['tid'] for x in r['raw_line_reads']})
        if mode in ('before_runtime','constructor_gap'):
            checks[mode+'_read_without_runtime_log']=len(sent)==len(raw)==2 and len(logs)==len(r['runtime_submit_calls'])==1 and r['early_line_read_without_runtime'] and sent[0]['value']==sent[1]['value'] and r['early_pose_sequence'] in r['original_reader_processed_sequences']
        else:
            c=r['runtime_submit_calls'][0]
            checks[mode+'_receipt_before_acceptance']=len(sent)==len(raw)==len(logs)==1 and (not c['before']['active'] if mode=='inactive_runtime' else c['packet']['generation']!=c['before']['generation']) and c['before']['barrier_sequence']==c['after']['barrier_sequence']
        summary[mode]=dict(sent_pose_lines=len(sent),independent_stdin_pose_reads=len(raw),runtime_pose_input_logs=len(logs),runtime_submit_calls=len(r['runtime_submit_calls']))
    checks['same_original_serve_body']=len({r['source_sha256'] for r in cases.values()})==len({r['original_serve_ast_sha256'] for r in cases.values()})==1
    return dict(checks=checks,synthetic_receipt_stage_control_pass=all(checks.values()),counts=summary,
                actual_case_specific_missing_occurrence_identified=False,old_protocol_qualification_pass=False,
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,
                limits=['Exact original serve body is compiled with injected I/O and fake hardware; the real TrackingRuntime methods execute beneath a state-observation wrapper. No GUI/model/replay/human/device test.',
                        'These cases establish possible receipt-stage omissions, not which occurrence is absent in the saved540/539 record.',
                        'Existing global identity/clock gate stays failed. No duplicate-payload endpoint or occurrence is removed to obtain qualification.'])


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==v for n,v in manifest.items())
    status=read(a.raw/'runs/synthetic01/result01.json');assert status['complete'] and not status['errors'] and status['lock_retained']
    cases={n:read(a.raw/'runs/synthetic01'/file) for n,file in status['cases'].items()};result=inspect(cases)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(not result['synthetic_receipt_stage_control_pass'])
