"""Full-bundle identity and observed overlap; never grants overhead calibration."""
def check_case(plan,value):
    m=value['model'];c=value['consumer'];calls=m['calls'];count=plan['model_calls'];ids=plan['frame_ids']
    checks=dict(complete=value.get('complete') and not value['errors'] and value['full_original_chain_exact'] and not value['worker_alive'],
                model_closed=m['closed'] and not m['errors'],
                exact_model_calls=len(calls)==len(value['model_result_sha256'])==count and [(x['ordinal'],x['frame_id'],x['logical_ms']) for x in calls]==[(i,ids[i%len(ids)],1000+50*i) for i in range(count)],
                ordered_calls=all(m['begin_ns']<=x['begin_ns']<=x['end_ns']<=m['end_ns'] for x in calls) and all(a['end_ns']<=b['begin_ns'] for a,b in zip(calls,calls[1:])),
                distinct_threads=c['tid']!=m['tid'],consumer_frames=c['frames']==plan['raw_after_last']-plan['raw_first'],
                overlapping_work=max(c['begin_ns'],m['begin_ns'])<min(c['end_ns'],m['end_ns']))
    overlap=[x['ordinal'] for x in calls if x['begin_ns']<c['end_ns'] and x['end_ns']>c['begin_ns']]
    return dict(checks=checks,identity_and_overlap_pass=all(checks.values()),model_calls_overlapping_consumer=overlap,
                consumer_wall_ms=(c['end_ns']-c['begin_ns'])/1e6,model_wall_ms=(m['end_ns']-m['begin_ns'])/1e6,
                model_close_overlaps_consumer=max(c['begin_ns'],m['close_begin_ns'])<min(c['end_ns'],m['close_end_ns']))

def compare(plan,a,b):
    cases=[check_case(plan,x) for x in (a,b)]
    checks=dict(both_identity_and_overlap=all(x['identity_and_overlap_pass'] for x in cases),same_decoded_frames=a['frame_evidence']==b['frame_evidence'],
                same_complete_model_results=a['model_result_sha256']==b['model_result_sha256'],same_chain_report=a['report_sha256']==b['report_sha256'])
    return dict(checks=checks,fixed_bundle_identity_pass=all(checks.values()),cases=cases,
                same_model_overlap_sequence=cases[0]['model_calls_overlapping_consumer']==cases[1]['model_calls_overlapping_consumer'],
                model_close_outside_consumer=not any(x['model_close_overlaps_consumer'] for x in cases),
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)
