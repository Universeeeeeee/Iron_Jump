"""Known CreateThread entry + independent live system query + delivered ETW bytes."""
import base64
from collections import defaultdict
import hashlib
import json
from pathlib import Path,PureWindowsPath
import struct
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def verify_entry(event,expected):
    data=base64.b64decode(event['payload'])
    if event['version']!=3 or not event['flags']&0x40 or len(data)!=74:raise ValueError('Unqualified thread layout')
    encoded=struct.pack('<Q',expected);offsets=[i for i in range(len(data)-7) if data[i:i+8]==encoded]
    if offsets!=[48]:raise ValueError('Known entry not unique at candidate offset48')
    return struct.unpack_from('<Q',data,48)[0]

if __name__=='__main__':
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from analyze import clock_residual_ms,PLAN
    plan=read(HERE/'plan01.json');f=read(HERE/'fixture01.json');m=read(HERE/'metadata01.json');status=read(HERE/'status01.json');record=read(HERE/'record01.json')
    assert all(sha(ROOT/n)==v for n,v in plan['sources'].items())
    assert f['complete'] and not f['errors'] and f['gate_closed'] and len(f['threads'])==2
    assert status['complete'] and not status['errors'] and status['interval_before']==status['interval_after'] and record['cleanup_complete'] and record['stop_ok']
    assert m['target_pid']==f['pid'] and m['clock_type']==1 and m['qpc_frequency']==f['start']['frequency']
    assert all(m[k]==0 for k in ('header_events_lost','consumer_events_lost','buffers_lost'))
    assert not any(k.startswith('def2fe46') or (k.startswith('ce1dbfb4') and k.split('/')[1]!='34') or (k.startswith('3d6fa8d1') and k.split('/')[1] in ('36','50')) for k in m['shapes'])
    events=defaultdict(list);images=[]
    for line in (HERE/'events01.jsonl').open():
        e=json.loads(line);d=base64.b64decode(e['payload'])
        if e['provider'].startswith('3d6fa8d1') and e['opcode'] in (1,2):
            pid,tid=struct.unpack_from('<II',d);assert pid==f['pid'];events[tid].append(e)
        if e['provider'].startswith('2cb15d1d') and e['opcode']==10 and e['version'] in (2,3) and e['flags']&0x40 and len(d)>=58:
            base,size,pid,checksum=struct.unpack_from('<QQII',d);path=d[56:].decode('utf-16le').split('\0')[0]
            if pid==f['pid'] and PureWindowsPath(path).name.lower()=='entryoracle.dll':images.append(dict(base=base,size=size,path=path,qpc=e['qpc'],checksum=checksum))
    assert len(images)==1;module=images[0];rows=[];anchors=[f['start'],f['end']]
    for t in f['threads']:
        assert t['owner_pid']==f['pid'] and t['exit_before']==259 and t['exit_after']==t['expected_exit'] and t['exit_confirmed'] and t['handle_closed']
        assert t['query_status']==0 and t['query_size']==8 and t['queried_entry']==t['expected_entry']
        matched=sorted(events[t['tid']],key=lambda e:e['qpc']);assert [e['opcode'] for e in matched]==[1,2]
        assert matched[0]['qpc']<=t['query_before']['qpc_before']<=t['query_after']['qpc_after']<=matched[1]['qpc']
        for e in matched:assert verify_entry(e,t['expected_entry'])==t['queried_entry']
        assert module['qpc']<=matched[0]['qpc'] and module['base']<=t['expected_entry']<module['base']+module['size']
        anchors.extend([t['query_before'],t['query_after']]);rows.append(dict(tid=t['tid'],export=t['name'],entry=t['expected_entry'],rva=t['expected_entry']-module['base'],query_matches=True,start_and_end_payload_match=True,creation_100ns=t['creation_100ns']))
    residual=clock_residual_ms(anchors,m['clock_samples'],m['qpc_frequency']);assert residual<=PLAN['gates']['clock_residual_ms_max']
    result=dict(known_entry_control_pass=True,validated_payload_layout=dict(version=3,pointer_bits=64,length=74,entry_offset=48),threads=rows,module=module,dll_sha256=plan['dll_sha256'],clock_residual_ms=residual,
        loss={k:m[k] for k in ('header_events_lost','consumer_events_lost','buffers_lost')},actual_load_disturbance_pass=False,primary_root_identified=False,
        limits=['Only delivered74-byte x64 version3 Start/End payloads validated; reject other layouts until independently verified.','Entry address is a thread startup boundary, not its current stack, creator, GIL owner, CPU hotspot or responsibility function.','No PDB claim; export identity is supplied by our known native oracle and actual CreateThread argument.','Newly created threads in the previous untraced model window remain unattributed.'],
        sources={n:sha(HERE/n) for n in ['review.py','plan01.json','fixture01.json','events01.jsonl','metadata01.json']})
    with (HERE/'review01.json').open('x') as out:json.dump(result,out,indent=2)
    print(json.dumps(result,indent=2))
