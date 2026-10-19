"""Whole stream/occurrence links; no mailbox acceptance or overhead inference."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'gil_workload_observation'))
from workload import packet

canonical=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'))


def inspect(parent,child,workload,expected_sources):
    controls=parent['controls'];rows=child['rows'];events=child['events'];checks={}
    checks['one_control']=len(controls)==1
    if not checks['one_control']:return dict(checks=checks,wire_delivery_pass=False,counts={},limits=['Ambiguous control topology'])
    control=controls[0];chunks=[bytes.fromhex(x) for x in control['chunks']];writes=control['writes'];stream=b''.join(chunks);lines=stream.splitlines(keepends=True)
    checks['bound_original_child_sources']=child['source_sha256']==expected_sources
    checks['write_acceptance']=len(chunks)==len(writes) and bool(writes) and all(w['sequence']==i+1 and w['error'] is None and w['reported_accepted_bytes']==w['requested_bytes']==len(c) and hashlib.sha256(c).hexdigest()==w['requested_sha256'] and w['pid']==parent['pid'] and w['write_begin_ns']<=w['write_end_ns'] for i,(c,w) in enumerate(zip(chunks,writes)))
    checks['ASCII_LF_stream']=all(c.isascii() for c in chunks) and bool(lines) and all(x.endswith(b'\n') and not x.endswith(b'\r\n') for x in lines)
    checks['independent_read_receipts']=len(lines)==len(rows) and all(r['sequence']==i+1 and r['pid']==child['pid'] and r['read_begin_ns']<=r['read_end_ns'] and r['characters']==len(line) and r['text_utf8_sha256']==hashlib.sha256(line).hexdigest() for i,(line,r) in enumerate(zip(lines,rows)))
    checks['EOF_and_reader_exit']=child['observation_complete'] and child['reader_exited'] and child['eof'] and not child['errors'] and not child['read_errors'] and child['returncode']==0 and child['lock_retained']
    checks['PID_and_exit']=parent['pid']!=child['pid'] and len(control['started'])==len(control['finished'])==1 and control['started'][0]['gui_pid']==parent['pid'] and control['started'][0]['sdk_pid']==child['pid'] and control['finished'][0]['normal'] and control['finished'][0]['exit_code']==0 and control['finished'][0]['stop_confirmed'] and not control['errors']
    try:messages=[json.loads(x) for x in lines]
    except (ValueError,UnicodeError):messages=[]
    checks['JSON_contract']=len(messages)==len(lines) and all(isinstance(x,dict) for x in messages)
    poses={i+1:x['pose_packet'] for i,x in enumerate(messages) if 'pose_packet' in x}
    runtime=[x for x in events if x['stage']=='runtime_packet'];submits=[x for x in events if x['stage']=='runtime_submit'];mailbox=[x for x in events if x['stage']=='mailbox_submit']
    checks['known_stage_names']=all(x['stage'] in ('runtime_packet','runtime_submit','mailbox_submit') for x in events)
    seqs=[x['line_sequence'] for x in runtime];checks['runtime_occurrences']=seqs==sorted(set(seqs)) and all(s in poses for s in seqs)
    byseq={x['sequence']:x for x in rows}
    checks['reader_event_identity']=bool(rows) and len({x['tid'] for x in rows})==1 and rows[0]['tid']!=child['serve_tid'] and all(x['line_sequence'] in byseq and x['pid']==child['pid'] and x['tid']==byseq[x['line_sequence']]['tid'] and x['error'] is None and byseq[x['line_sequence']]['read_end_ns']<=x['begin_ns']<=x.get('end_ns',-1) for x in events)
    checks['nested_runtime_calls']=all(any(p['line_sequence']==x['line_sequence'] and p['begin_ns']<=x['begin_ns']<=x['end_ns']<=p['end_ns'] for p in runtime) for x in submits+mailbox)
    checks['nested_mailbox_calls']=all(any(p['line_sequence']==x['line_sequence'] and p['begin_ns']<=x['begin_ns']<=x['end_ns']<=p['end_ns'] for p in submits) for x in mailbox)
    relay=[x['packet'] for x in workload['rows']['relay_packets']];pose_logs=[x for x in workload['rows']['sdk_events'] if x['data']['event']=='pose_input']
    checks['relay_to_write_occurrences']=[canonical(x) for x in relay]==[canonical(packet(p)) for p in poses.values()]
    checks['runtime_to_original_pose_logs']=len(pose_logs)==len(runtime) and [canonical(x['data']['packet']) for x in pose_logs]==[canonical(packet(poses[s])) for s in seqs if s in poses]
    checks['GUI_role']=workload['pid']==parent['pid'] and all(w['tid']==control['started'][0]['tid'] for w in writes) if len(control['started'])==1 else False
    # FIFO line boundaries identify each receipt, even with duplicate contents
    # and arbitrary write chunk boundaries. Only causal bounds cross processes.
    line_first_chunks=[];position=0;chunk_starts=[]
    for i,c in enumerate(chunks):chunk_starts.append((position,position+len(c),i));position+=len(c)
    position=0
    for line in lines:
        candidates=[i for begin,end,i in chunk_starts if begin<=position<end];line_first_chunks.append(candidates[0] if len(candidates)==1 else None);position+=len(line)
    lower=[writes[i]['write_begin_ns']-r['read_end_ns'] for i,r in zip(line_first_chunks,rows) if i is not None and i<len(writes)]
    upper=[p['observed_ns']-e['begin_ns'] for p,e in zip(pose_logs,runtime)]
    for call in workload['rows']['sdk_events']:
        if call['data']['event']=='sdk_call':upper.append(call['observed_ns']-round(call['data']['returned_at']*1e9))
    clock=None if not lower or not upper else dict(host_minus_child_ns_bounds=[max(lower),min(upper)],uncertainty_ns=min(upper)-max(lower),zero_offset_compatible=max(lower)<=0<=min(upper))
    checks['independent_causal_clock']=clock is not None and clock['zero_offset_compatible'] and checks['independent_read_receipts'] and checks['runtime_to_original_pose_logs']
    no_runtime=[s for s in poses if s not in seqs]
    # This classification is valid only for this fully closed, error-free
    # original serve transcript. Absence in an incomplete trace proves nothing.
    complete=all(checks.values())
    return dict(checks=checks,wire_delivery_pass=complete,counts=dict(write_calls=len(writes),text_lines=len(rows),pose_lines=len(poses),runtime_packet_calls=len(runtime),runtime_submit_calls=len(submits),mailbox_submit_calls=len(mailbox)),child_clock=clock,
                read_pose_sequences_without_runtime=no_runtime if complete else [],unclassified_pose_sequences=no_runtime if not complete else [],
                no_runtime_classification='Original serve runtime-is-None branch, conditional on whole closed transcript and unchanged bound sources' if complete else 'Unknown; incomplete/failed evidence',
                actual_load_disturbance_pass=False,field_attribution_ready=False,
                limits=['Normal mailbox return is not business acceptance or SDK physical actuation.','New receipt observer may alter startup, inference selection and GIL behavior; overhead unqualified.','Old strict relay/runtime equality gate remains separately reported and is never upgraded by these new receipts.'])
