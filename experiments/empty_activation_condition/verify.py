"""Verify unchanged complete work and the actually delivered requested overlap."""
def check(plan,r):
    c=r['consumer'];m=r['model'];calls=m['calls'];variant=r['variant'];overlap=max(c['begin_ns'],m['begin_ns'])<min(c['end_ns'],m['end_ns'])
    checks=dict(complete=r.get('complete') and not r['errors'] and r['full_original_chain_exact'] and not r['worker_alive'],
        model_closed=m['closed'] and not m['errors'],distinct_threads=c['tid']!=m['tid'],
        model_ready=m['ready_ns']<=min(c['begin_ns'],m['begin_ns']),
        exact_model_calls=len(calls)==len(r['model_result_sha256'])==plan['model_calls'] and [(x['ordinal'],x['frame_id'],x['logical_ms']) for x in calls]==[(i,plan['frame_ids'][i%len(plan['frame_ids'])],1000+50*i) for i in range(plan['model_calls'])],
        ordered_calls=all(m['begin_ns']<=x['begin_ns']<=x['end_ns']<=m['end_ns'] for x in calls) and all(a['end_ns']<=b['begin_ns'] for a,b in zip(calls,calls[1:])),
        consumer_frames=c['frames']==plan['raw_after_last']-plan['raw_first'],
        requested_schedule=(overlap if variant=='concurrent' else m['begin_ns']>=c['end_ns'] if variant=='serial' else False),
        close_after_work=m['close_begin_ns']>=max(c['end_ns'],m['end_ns']),
        original_process_accounting=r['process_accounting']['accounting_pass'])
    points=r['consumer_progress'];checks['fixed_progress']= [x['frames'] for x in points]==plan['progress_frames'] and all(x['raw_last']==plan['raw_first']+x['frames']-1 and c['begin_ns']<=x['host_ns']<=c['end_ns'] and 0<=x['thread_cpu_ns']<=c['thread_cpu_ns'] for x in points) and all(a['host_ns']<=b['host_ns'] and a['thread_cpu_ns']<=b['thread_cpu_ns'] for a,b in zip(points,points[1:]))
    return dict(checks=checks,pass_all=all(checks.values()),actual_overlap=overlap,consumer_wall_ms=(c['end_ns']-c['begin_ns'])/1e6)

def identity(r):return (r['frame_evidence'],r['model_result_sha256'],r['report_sha256'])
