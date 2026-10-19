def verify_runtime(activation,variant,session):
    cfg=activation['configuration'];rows=sorted(activation['runtime_context'],key=lambda v:(v['role'],v['ordinal']))
    if cfg['variant']!=variant or activation['at_end']!=cfg['after']:raise ValueError('QoS identity changed')
    if not activation['original_method_unchanged'] or not activation['original_module_unchanged']:raise ValueError('Original method changed')
    if activation['context']['session_id']!=session:raise ValueError('Different session')
    for role in ('consumer','model','gui'):
        selected=[v for v in rows if v['role']==role]
        if [v['ordinal'] for v in selected]!=[1,100]:raise ValueError('Incomplete bounded contexts')
        if len({v['tid'] for v in selected})!=1:raise ValueError('Role thread changed')
    if len(rows)!=6:raise ValueError('Unexpected runtime contexts')
    for v in rows:
        if v['session_id']!=session or v['priority_class']!=16384:raise ValueError('Execution context changed')
        if not 0<=v['end_ns']-v['begin_ns']<=50000000:raise ValueError('Context read too long')
        if not v['process']['success'] or not v['thread']['success']:raise ValueError('Unconfirmed policy')
        if any(v['process'][k]!=cfg['after'][k] for k in ('version','control_mask','state_mask')):raise ValueError('Process QoS changed')
    return dict(verified=True,foreground_self=[v['foreground_pid']==v['pid'] for v in rows],thread_policies=[dict(role=v['role'],ordinal=v['ordinal'],policy=v['thread']) for v in rows])
