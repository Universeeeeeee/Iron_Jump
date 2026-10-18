"""Qualify synthetic preparse text receipts, not business acceptance or raw pipe delivery."""
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));from receipts import compare_ascii_lines
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def inspect(cases):
    checks={};counts={}
    for name,r in cases.items():
        sent=r['sender_write_receipts'];recv=r['preparse_text_receipts'];original=r['raw_line_reads'];logs=[x for x in r['original_replies'] if x['value'].get('tracking_log',{}).get('event')=='pose_input']
        links=compare_ascii_lines(sent,recv)
        checks[name+'_independent_text_receipts']=(links['receipt_link_pass'] and r['text_eof_observed'] and not r['text_read_errors'] and len(recv)==len(original) and all(hashlib.sha256(x['line'].encode('utf-8')).hexdigest()==y['text_utf8_sha256'] for x,y in zip(original,recv)))
        checks[name+'_line_preserved']=(len(original)==len(r['input_sent']) and all(json.loads(x['line'])==y['value'] for x,y in zip(original,r['input_sent'])))
        checks[name+'_clean']=r['returncode']==0 and not r['errors'] and not r['serve_thread_alive']
        if name in ('before_runtime','constructor_gap'):
            checks[name+'_runtime_omission_located']=(r['early_line_read_without_runtime'] and len(logs)==1 and len([x for x in r['input_sent'] if 'pose_packet' in x['value']])==2 and r['early_pose_sequence'] in r['original_reader_processed_sequences'])
        counts[name]=dict(sender_writes=len(sent),preparse_text_receipts=len(recv),runtime_pose_input_logs=len(logs))
    return dict(checks=checks,synthetic_preparse_receipt_control_pass=all(checks.values()),counts=counts,
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,
                previous_540_539_occurrence_recovered=False,
                limits=['Observer-local sequence identifies repeated line occurrences in these complete synthetic transcripts; no sequence field is inserted in the original wire.',
                        'Text receipt is after TextIO decoding and before original JSON parsing. Only tested ASCII LF framing permits requested-byte and text-digest comparison; partial writes/CRLF translation remain failures.',
                        'QProcess acceptance/buffering and OS pipe delivery are different stages. This harness does not certify real QProcess buffering or delivery.',
                        'Hashing/recording adds work and can release the GIL. No actual replay entry/SDK launcher has been changed or deployed, and observer perturbation is unqualified.',
                        'Old missing occurrences cannot be reconstructed from new synthetic receipts. Old global identity/clock gates stay failed.'])


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==v for n,v in manifest.items())
    plan=read(a.raw/'plan01.json');assert all(sha(a.raw/n)==v for n,v in plan['sources'].items())
    status=read(a.raw/'runs/synthetic01/result01.json');assert status['complete'] and not status['errors'] and status['lock_retained']
    cases={n:read(a.raw/'runs/synthetic01'/file) for n,file in status['cases'].items()};assert all(c['source_sha256']==plan['existing_sources']['camera/control_service.py'] for c in cases.values())
    result=inspect(cases)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(not result['synthetic_preparse_receipt_control_pass'])
