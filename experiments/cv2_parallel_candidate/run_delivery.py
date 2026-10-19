"""Exactly default then one-thread delivery/semantics windows; no performance verdict."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import base64
import struct
from types import SimpleNamespace
from delivery import classify_starts,gate

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
if __name__=='__main__':
    plan=read(HERE/'plan01.json');assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
    stage=HERE/'runs/delivery01';stage.mkdir(parents=True,exist_ok=False);(stage/'active.lock').mkdir();status=dict(cases=[],errors=[],complete=False,performance_started=False)
    with (stage/'controller.json').open('x') as f:json.dump(dict(pid=__import__('os').getpid()),f)
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from winapi import profile_interval
    from analyze import clock_residual_ms,PLAN
    controller=module('cv2_delivery_controller',HERE/'capture.py');verifier=module('cv2_original_work_verify',ROOT/'experiments/fixed_overlap_comparison/verify.py')
    reference=verifier.identity(read(HERE/'reference01.json'));reviews={};metas={}
    life_parser=module('cv2_lifetime_parser',ROOT/'experiments/thread_lifecycle_review/review.py')
    try:
        interval=profile_interval();assert sha(Path(plan['reader']))==plan['reader_sha256']
        for case in plan['delivery_cases']:
            controller.main(SimpleNamespace(mode='lifecycle',output=stage/case/'window',case=case,targets=None,seconds=None))
            r=read(HERE/'child/runs'/case/'result.json');meta=read(HERE/(case+'_meta.json'));metas[case]=meta
            valid=verifier.check(read(HERE/'child/plan01.json'),r);assert valid['pass_all'] and verifier.identity(r)==reference
            assert meta['workload_returncode']==0 and not meta['errors'] and meta['sources_unchanged'] and meta['cv2_binary_unchanged'] and meta['resize_wrapper_restored']
            args=[plan['reader'],str(stage/case/'window/trace.etl'),str(meta['pid']),str(r['consumer']['tid'])+','+str(r['model']['tid']),str(stage/case/'decoded')]
            decoded=subprocess.run(args,capture_output=True);assert decoded.returncode==0,(decoded.stdout,decoded.stderr)
            m=read(stage/case/'decoded/metadata.json');record=read(stage/case/'window/record.json')
            assert m['target_pid']==meta['pid']==r['process_before']['pid'] and m['clock_type']==1 and m['qpc_frequency']==record['start']['frequency']
            assert all(m[k]==0 for k in ('header_events_lost','consumer_events_lost','buffers_lost')) and record['cleanup_complete'] and record['stop_ok']
            assert not any(k.startswith('def2fe46') or (k.startswith('ce1dbfb4') and k.split('/')[1]!='34') or (k.startswith('3d6fa8d1') and k.split('/')[1] in ('36','50')) for k in m['shapes'])
            anchors=[record['start'],record['end']];freq=m['qpc_frequency'];residual=clock_residual_ms(anchors,m['clock_samples'],freq);assert residual<=PLAN['gates']['clock_residual_ms_max']
            lo=max(x['perf_before_ns']-x['qpc_after']*10**9//freq for x in anchors);hi=min(x['perf_after_ns']-x['qpc_before']*10**9//freq for x in anchors);assert lo<=hi
            events=[json.loads(x) for x in (stage/case/'decoded/events.jsonl').read_text().splitlines()]
            role_lifetimes={}
            for role in ('consumer','model'):
                tid=r[role]['tid'];items=[]
                for event in events:
                    if event['provider'].startswith('3d6fa8d1') and event['opcode'] in (1,2,3,4):
                        data=base64.b64decode(event['payload']);assert event['version']==3 and len(data)>=8
                        owner,number=struct.unpack_from('<II',data)
                        if owner==meta['pid'] and number==tid:items.append((event['qpc'],event['opcode']))
                matched=[x for x in life_parser.lifetimes(items) if x['actual_creation'] and x['actual_exit'] and x['begin']*10**9//freq+hi<=r[role]['begin_ns'] and r[role]['end_ns']<=x['end']*10**9//freq+lo]
                assert len(matched)==1;role_lifetimes[role]=matched[0]
            found=classify_starts(events,meta['pid'],r['process_before']['end_ns'],r['process_after']['begin_ns'],freq,lo,hi,meta['cv2_image'])
            assert not found['unknown']
            if case=='default':assert found['cv2_starts']
            else:assert not found['cv2_starts']
            reviews[case]=dict(full_original_work_exact=True,resized_count=len(meta['resized']),configured_before=meta['configured_before'],configured_after=meta['configured_after'],clock_residual_ms=residual,lifecycle=found,role_lifetimes=role_lifetimes)
            status['cases'].append(case);assert profile_interval()==interval
            print(json.dumps(dict(case=case,complete=True,new_cv2_threads=len(found['cv2_starts']),resized_count=len(meta['resized']))),flush=True)
        status['gate']=gate(reviews['default']['lifecycle'],reviews['one']['lifecycle'],metas['default']['resized'],metas['one']['resized'],plan['model_calls']);assert all(status['gate'].values())
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        status['reviews']=reviews
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(dict(complete=status['complete'],errors=status['errors'],performance_started=False)),flush=True);raise SystemExit(bool(status['errors']))
