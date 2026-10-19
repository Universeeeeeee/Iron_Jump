"""Old CPU ETL expanded-thread witnesses only; no hotspot/time-share attribution."""
import base64,hashlib,importlib.util,json,struct
from pathlib import Path
from collections import Counter,defaultdict
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('original_cpu_stack_quality',ROOT/'experiments/native_stack_capture/analyze.py');analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)
def events(path):return [json.loads(s) for s in path.read_text().splitlines()]
def fingerprint(rows,prefix):return Counter((e['qpc'],e['cpu'],e['header_pid'],e['header_tid'],e['opcode'],e['version'],e['payload']) for e in rows if e['provider'].startswith(prefix))
def module_at(ip,modules):
    found={(m['base'],m['size'],m.get('sha256'),m.get('path',m['recorded_path'])) for m in modules if m['base']<=ip<m['base']+m['size']}
    if len(found)!=1:return dict(address=ip,module=None,rva=None,sha256=None,ambiguous=bool(found))
    base,size,digest,path=next(iter(found));return dict(address=ip,module=path,rva=ip-base,sha256=digest,ambiguous=False)
if __name__=='__main__':
    plan=read(HERE/'expanded_review_plan01.json');assert all(sha(ROOT/n)==v for n,v in plan['bindings'].items())
    original=ROOT/'experiments/native_stack_capture/runs/field_cpu01_round01/split01/11948';old=events(original/'decoded/events.jsonl');new=events(HERE/'runs/events.jsonl');symbols=read(original/'symbols03.json')
    assert sha(original/'decoded/events.jsonl')==symbols['events_sha256']
    for provider in ('def2fe46','2cb15d1d','3d6fa8d1','3d6fa8d0'):assert fingerprint(old,provider)==fingerprint(new,provider),'Saved stack/image/lifetime inputs changed'
    old_profiles=Counter(json.dumps(e,sort_keys=True) for e in old if e['provider'].startswith('ce1dbfb4') and e['opcode']==46)
    new_profiles=Counter(json.dumps(e,sort_keys=True) for e in new if e['provider'].startswith('ce1dbfb4') and e['opcode']==46)
    assert not old_profiles-new_profiles
    meta=read(HERE/'runs/metadata.json');assert meta['header_events_lost']==meta['buffers_lost']==meta['consumer_events_lost']==0
    fixture=read(original/'fixture/fixture.json');begin=max(t['before']['clock']['qpc_after'] for t in fixture['threads'].values());end=min(t['after']['clock']['qpc_before'] for t in fixture['threads'].values())
    stacks=defaultdict(list);profile=[]
    for e in new:
        data=base64.b64decode(e['payload'])
        if e['provider'].startswith('def2fe46'):
            q,pid,tid=struct.unpack_from('<QII',data);assert pid==11948;stacks[q,tid].append(struct.unpack_from('<'+'Q'*((len(data)-16)//8),data,16))
        if e['provider'].startswith('ce1dbfb4') and e['opcode']==46:
            assert e['version']==2 and len(data)==16 and e['flags']&0x40
            ip,tid,count=struct.unpack_from('<QIH',data);assert count==1;profile.append((e['qpc'],tid,ip,bool(data[14]&3)))
    names={t['before']['tid']:name for name,t in fixture['threads'].items()};rows=[];witnesses={};audit=Counter()
    for q,tid,ip,nonprocess in profile:
        if not begin<=q<=end:audit['outside_common_counter_core']+=1;continue
        parts=stacks.get((q,tid),[]);info=analysis.stack_info(parts,symbols['addresses']);matched=any(ip in p for p in parts);location=module_at(ip,symbols['modules'])
        usable=matched and info['root_complete'] and not info['ambiguous'] and not nonprocess and location['module'] is not None
        row=dict(qpc=q,tid=tid,original_named_role=names.get(tid),ip=location,ip_in_linked_stack=matched,root_complete=info['root_complete'],stack_ambiguous=info['ambiguous'],nonprocess=nonprocess,individual_witness_usable=usable)
        rows.append(row);audit['core_samples']+=1
        if not matched:audit['ip_mismatches_retained']+=1
        if nonprocess:audit['nonprocess_retained']+=1
        if usable:
            key=(tid,location['module'])
            if key not in witnesses:witnesses[key]=dict(**row,frames=info['frames'])
    old_acceptance=read(ROOT/'experiments/native_stack_capture/field_reviews/20261017_field_cpu01/round01/acceptance.json');assert not old_acceptance['measurement_acceptance_pass']
    result=dict(scope='Offline expanded decoding of the same oldCPU ETL. Original global acceptance stays failed; examples are not cost ranks orCPUshares.',target_pid=11948,source_etl_sha256=read(HERE/'offline_decode_plan01.json')['etl_sha256'],old_profile_samples=sum(old_profiles.values()),expanded_profile_samples=sum(new_profiles.values()),expanded_tids=read(HERE/'expanded_targets01.json')['expanded_tids'],old_stack_image_lifetime_bytes_preserved=True,cached_symbol_reuse_basis='Original eventSHA matches symbol input, and all stack/image/lifetime records are identical after expansion. Newly unmatchedIPs keep module/RVA without invented symbol.',
        counter_common_core_qpc=[begin,end],audit=dict(audit),individual_examples=list(witnesses.values()),all_core_profile_rows=rows,original_acceptance=old_acceptance,
        limits=['No before/after CPUcounter reference for newly decoded native workers; no per-thread CPU estimate.','This is PID11948 from the original field CPU window, not the PID23008/14620 counter windows. No cross-PID/TID role orCPUtime join.','An executing module orRVA does not identify a business function, internal operator, GIL owner orhold duration.','Global stack/actual-load gates stay failed; no root percentage ororiginal failure reclassification.'],new_capture=False,primary_root_identified=False,bindings=plan['bindings'])
    with (HERE/'expanded_cpu_review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(old_profile=result['old_profile_samples'],expanded_profile=result['expanded_profile_samples'],audit=result['audit'],examples=[dict(tid=v['tid'],named=v['original_named_role'],module=v['ip']['module'],rva=v['ip']['rva']) for v in witnesses.values()]),indent=2))
