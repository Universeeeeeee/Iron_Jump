"""Accepted Qt write stream vs independent child text lines; no packet acceptance claim."""
import hashlib
import json
from pathlib import Path

read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def inspect(record,child):
    parts=[bytes.fromhex(x) for x in record['write_argument_hex']];writes=record['write_rows'];reads=child['rows']
    accepted=all(x['error'] is None and x['reported_accepted_bytes']==len(p)==x['requested_bytes'] and hashlib.sha256(p).hexdigest()==x['requested_sha256'] for p,x in zip(parts,writes)) and len(parts)==len(writes)
    stream=b''.join(parts);lines=stream.splitlines(keepends=True)
    checks=dict(all_writes_accepted=accepted,ASCII_LF_contract=all(p.isascii() for p in parts) and all(x.endswith(b'\n') and not x.endswith(b'\r\n') for x in lines),
                complete_line_stream=len(lines)==len(reads) and all(len(x)==r['characters'] and hashlib.sha256(x).hexdigest()==r['text_utf8_sha256'] for x,r in zip(lines,reads)),
                read_ordinals=[x['sequence'] for x in reads]==list(range(1,len(reads)+1)),
                child_EOF=child['eof'] and not child['read_errors'],
                stopped_and_closed=record['case_complete'] and record['closed'] and record['stop_confirmed'] and record['child_exit_code']==0 and not record['echo_still_running'] and not record['errors'],
                command_acks=record['acks']==[['tracking_start',0],['tracking_stop',0]])
    if record['mode']=='split':checks['split_writes_not_line_count']=len(parts)>len(lines)
    if record['mode']=='bad_json':checks['bad_JSON_still_receipted']=sum(not x['parsed'] for x in child['parsed'])==1
    else:checks['all_JSON_parsed']=all(x['parsed'] for x in child['parsed'])
    return dict(checks=checks,synthetic_QProcess_receipt_pass=all(checks.values()),write_calls=len(parts),text_lines=len(lines),child_receipts=len(reads))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==v for n,v in manifest.items())
    status=read(a.raw/'runs/synthetic01/result01.json');assert status['complete'] and not status['errors'] and status['lock_retained']
    cases={name:inspect(read(a.raw/'runs/synthetic01'/name/'record01.json'),read(a.raw/'runs/synthetic01'/name/'child_receipts.json')) for name in status['cases']}
    result=dict(cases=cases,QProcess_synthetic_controls_pass=all(x['synthetic_QProcess_receipt_pass'] for x in cases.values()),
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,
                limits=['Original CameraControlService and real QCoreApplication/QProcess, but child is a protocol echo, not the real SDK.',
                        'Write return confirms acceptance into Qt buffering. Child independent receipts confirm delivered text only for these completed synthetic transcripts.',
                        'A split write is a stream chunk, not a complete message. Ordered accepted chunks are compared to child line receipts; no digest/line normalization.',
                        'No real SDK launcher/replay deployed; no model, sensor/camera acquisition, human, Run or optimization AB; old540/539 remains unresolved/failed.'])
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(not result['QProcess_synthetic_controls_pass'])
