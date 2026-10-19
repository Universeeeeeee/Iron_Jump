"""Independently review immutable delivery data; retain preflight enforcement failure."""
import hashlib
import importlib.util
import json
from pathlib import Path
from delivery import classify_starts,gate

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    raw=HERE/'runs/delivery_evidence01';manifest=read(raw/'manifest_delivery01.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan01.json');assert sha(raw/'plan01.json')==sha(HERE/'plan01.json') and all(sha(raw/n)==v for n,v in plan['sources'].items())
    spec=importlib.util.spec_from_file_location('cv2_work_check',ROOT/'experiments/fixed_overlap_comparison/verify.py');verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)
    status=read(raw/'runs/delivery01/status.json');assert status['complete'] and not status['errors'] and status['cases']==plan['delivery_cases']
    reference=verify.identity(read(raw/'reference01.json'));metas={};found={};full={}
    for case in plan['delivery_cases']:
        meta=read(raw/(case+'_meta.json'));r=read(raw/'child/runs'/case/'result.json');folder=raw/'runs/delivery01'/case
        assert verify.check(read(raw/'child/plan01.json'),r)['pass_all'] and verify.identity(r)==reference
        assert not meta['errors'] and meta['workload_returncode']==0 and meta['sources_unchanged'] and meta['cv2_binary_unchanged']
        m=read(folder/'decoded/metadata.json');record=read(folder/'window/record.json');freq=m['qpc_frequency'];anchors=[record['start'],record['end']]
        assert all(m[k]==0 for k in ('header_events_lost','consumer_events_lost','buffers_lost')) and record['cleanup_complete'] and record['stop_ok']
        lo=max(a['perf_before_ns']-a['qpc_after']*10**9//freq for a in anchors);hi=min(a['perf_after_ns']-a['qpc_before']*10**9//freq for a in anchors);assert lo<=hi
        events=[json.loads(x) for x in (folder/'decoded/events.jsonl').read_text().splitlines()]
        found[case]=classify_starts(events,meta['pid'],r['process_before']['end_ns'],r['process_after']['begin_ns'],freq,lo,hi,meta['cv2_image']);assert found[case]==status['reviews'][case]['lifecycle']
        full[case]=classify_starts(events,meta['pid'],record['start']['perf_before_ns'],record['end']['perf_after_ns'],freq,lo,hi,meta['cv2_image'])
        metas[case]=meta
    checks=gate(found['default'],found['one'],metas['default']['resized'],metas['one']['resized'],plan['model_calls']);assert all(checks.values()) and checks==status['gate']
    post=read(HERE/'windows_tests_post01.json');assert post['post_capture'] and 'Ran 22 tests' in post['output'] and post['output'].strip().endswith('OK')
    result=dict(observed_delivery_and_semantics_pass=True,prospective_windows_preflight_passed=False,post_capture_windows_tests_passed=True,
        preflight_enforcement_failure_preserved=True,gate=checks,whole_trace_supplement=full,
        configured_counts={k:dict(before=m['configured_before'],after=m['configured_after']) for k,m in metas.items()},
        actual_work_roi_thread_counts={k:len(v['cv2_starts']) for k,v in found.items()},resized_pixels_compared=plan['model_calls'],
        performance_claim=False,performance_started=False,actual_load_disturbance_pass=False,primary_root_identified=False,
        limits=['The failed prospective Windows test gate remains failed; post-capture tests do not rewrite it.','These are execution-delivery and exact-semantics observations, not speed or field qualification.','Lifecycle entry module does not identify a current hotspot or GIL owner.','Future performance requires a new explicit passed preflight marker bound to that new plan; never continue after a failed shell step.'],
        bindings={n:sha(HERE/n) for n in ['plan01.json','review_delivery.py','preflight_failure01.json','windows_tests_post01.json']})
    with (HERE/'delivery_review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(gate=checks,whole_trace_cv2_counts={k:len(v['cv2_starts']) for k,v in full.items()},whole_trace_unknown_counts={k:len(v['unknown']) for k,v in full.items()},prospective_windows_preflight_passed=False,post_capture_windows_tests_passed=True),indent=2))
