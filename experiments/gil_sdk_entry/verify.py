"""Qualify only synthetic stage observations; mailbox call is not business acceptance."""
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('qprocess_stream_verify',HERE.parent/'gil_qprocess_receipts/verify.py');prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)


def inspect(record,child):
    r=dict(record,echo_still_running=record['child_still_running'])
    # Reuse only the independent accepted-stream/ordinal checks, not echo ACKs.
    c=dict(child,read_errors=child['read_errors'],parsed=[])
    transport=prior.inspect(r,c)['checks'];events=child['events'];rows=child['rows'];byseq={x['sequence']:x for x in rows}
    mode=record['mode'];targets=record['target_sequences'];invalid=mode in ('bad_json','bad_packet')
    expected_runtime=targets[1:] if mode in ('before_runtime','constructor_gap') else ([] if mode=='bad_json' else targets)
    runtime=[x for x in events if x['stage']=='runtime_packet'];submits=[x for x in events if x['stage']=='runtime_submit'];mailbox=[x for x in events if x['stage']=='mailbox_submit']
    lines=b''.join(bytes.fromhex(x) for x in record['write_argument_hex']).splitlines()
    expected_packets=[json.loads(lines[n-1])['pose_packet'] for n in expected_runtime if mode!='bad_packet']
    expected_mailbox=[]
    if mode in ('before_runtime','constructor_gap','active','old_barrier'):expected_mailbox=[expected_runtime[0]]*2
    checks={name:transport[name] for name in ('all_writes_accepted','ASCII_LF_contract','complete_line_stream','read_ordinals')}
    checks.update(child_terminated=child['reader_exited'] and record['case_complete'] and record['closed'] and record['child_exit_code']==0 and record.get('child_exit_normal') is True and not record['child_still_running'] and record['hardware_closed'] and record['stop_confirmed'] and child['lock_retained'] and not record['harness_errors'],
                  separate_PIDs=bool(rows) and child['pid']==record.get('QProcess_child_pid') and all(x['pid']==child['pid'] and x['pid']!=record['write_rows'][0]['pid'] and x['tid']!=child['serve_tid'] for x in rows),
                  original_input_error_preserved=(len(record['errors'])==1 and '控制输入失败' in record['errors'][0]) if invalid else not record['errors'],
                  EOF_qualification_preserved=(not child['eof'] and not child['observation_complete']) if invalid else child['eof'] and child['observation_complete'],
                  runtime_line_occurrences=[x['line_sequence'] for x in runtime]==expected_runtime,
                  mailbox_line_occurrences=[x['line_sequence'] for x in mailbox]==expected_mailbox,
                  runtime_submit_occurrences=[x['line_sequence'] for x in submits]==expected_mailbox,
                  original_pose_log_count=sum(x.get('event')=='pose_input' for x in record['logs'])==len(expected_runtime)-(1 if mode=='bad_packet' else 0),
                  original_pose_log_payloads=[x['packet'] for x in record['logs'] if x.get('event')=='pose_input']==expected_packets,
                  event_error_preserved=[(x['stage'],x['error']) for x in events if x['error']] == ([('runtime_packet','KeyError')] if mode=='bad_packet' else []),
                  read_errors_absent=not child['errors'] and not child['read_errors'])
    checks['event_identity_and_bounds']=all(x['line_sequence'] in byseq and x['pid']==child['pid'] and x['tid']==byseq[x['line_sequence']]['tid'] and byseq[x['line_sequence']]['read_end_ns']<=x['begin_ns']<=x.get('end_ns',-1) for x in events)
    checks['nested_call_bounds']=all(any(p['line_sequence']==x['line_sequence'] and p['begin_ns']<=x['begin_ns']<=x['end_ns']<=p['end_ns'] for p in runtime) for x in submits+mailbox)
    checks['mailbox_inside_submit']=all(any(p['line_sequence']==x['line_sequence'] and p['begin_ns']<=x['begin_ns']<=x['end_ns']<=p['end_ns'] for p in submits) for x in mailbox)
    return dict(checks=checks,synthetic_entry_pass=all(checks.values()),text_lines=len(rows),runtime_packet_calls=len(runtime),runtime_submit_calls=len(submits),mailbox_submit_calls=len(mailbox),
                actual_load_disturbance_pass=False,field_attribution_ready=False,
                scope='Original imported serve/runtime/mailbox with fake native hardware. A normal mailbox submit return is not proof of state mutation, pose acceptance, or SDK action. Bad input terminates reader before EOF; that observation remains incomplete.')
