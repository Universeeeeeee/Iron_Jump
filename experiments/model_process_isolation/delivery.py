def verify_child(parent,child,reference_hashes,parent_pid):
    calls=child['calls'];outer=parent['model']['calls']
    if child['pid']==parent_pid or child['errors'] or not child['closed']:raise ValueError('Child identity or completion failed')
    if child['frame_sha256']!=reference_hashes:raise ValueError('Prepared pixels changed')
    if len(calls)!=220 or len(outer)!=220:raise ValueError('Incomplete real model work')
    if child['ready_ns']>parent['model']['ready_ns']:raise ValueError('Readiness boundary mismatch')
    for i,(inside,outside) in enumerate(zip(calls,outer)):
        if inside['ordinal']!=i or inside['slot']!=i%len(reference_hashes) or inside['timestamp_ms']!=1000+50*i:raise ValueError('Model call identity changed')
        if not outside['begin_ns']<=inside['begin_ns']<=inside['end_ns']<=outside['end_ns']:raise ValueError('IPC/real call brackets mismatch')
    c=parent['consumer']
    overlap=max(c['begin_ns'],calls[0]['begin_ns'])<min(c['end_ns'],calls[-1]['end_ns'])
    if not overlap:raise ValueError('No actual cross-process overlap')
    a,b=child['process_before'],child['process_after']
    if a['pid']!=b['pid'] or a['pid']!=child['pid'] or a['creation_100ns']!=b['creation_100ns']:raise ValueError('Child accounting identity changed')
    if not a['end_ns']<=calls[0]['begin_ns']<=calls[-1]['end_ns']<=b['begin_ns']:raise ValueError('Child accounting coverage failed')
    if any(b[k]<a[k] for k in ('kernel_100ns','user_100ns','cycles')):raise ValueError('Child accounting regressed')
    return dict(separate_pid=True,actual_model_overlap=True,complete_model_calls=220,parent_model_thread_is_ipc_proxy=True,
                child_process_cpu_ms=(b['kernel_100ns']+b['user_100ns']-a['kernel_100ns']-a['user_100ns'])/10000,
                child_process_cycles=b['cycles']-a['cycles'],child_pid=child['pid'],child_model_tid=child['tid'],performance_qualification=False)
