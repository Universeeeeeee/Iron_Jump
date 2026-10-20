"""Validate GUI/consumer in one process and the model in the vision child."""

def check(rows):
    expected={(role,n) for role in ('gui','model','consumer') for n in (59904,65904)}
    assert len(rows)==6 and {(r['role'],r['ordinal']) for r in rows}==expected
    assert all('error' not in r and r['after_original_call'] and r['session_id']!=0 and r['priority_class']==16384
        and 0<=r['end_ns']-r['begin_ns']<=50000000 and r['process']['success'] and r['thread']['success'] for r in rows)
    assert all(r['completed_sample'] is not None and r['ordinal']<=r['completed_sample']<=r['ordinal']+19 if r['role']=='consumer'
        else r['source_due_ns'] is not None and r['begin_ns']>=r['source_due_ns'] for r in rows)
    by={role:{r['pid'] for r in rows if r['role']==role} for role in ('gui','model','consumer')}
    assert all(len(v)==1 for v in by.values()) and by['consumer']==by['gui'] and by['model']!=by['gui']
    tids={role:{(r['pid'],r['tid']) for r in rows if r['role']==role} for role in by}
    assert all(len(v)==1 for v in tids.values()) and len(set().union(*tids.values()))==3
    gui_pid=next(iter(by['gui']))
    return dict(context_reads_pass=True,role_pids={k:next(iter(v)) for k,v in by.items()},
        foreground_gui={f"{r['role']}/{r['ordinal']}":r['foreground_pid']==gui_pid for r in rows},
        policy={f"{r['role']}/{r['ordinal']}":dict(process=r['process'],thread=r['thread']) for r in rows},
        scope='Two phase checkpoints after original calls in GUI/consumer and after child model inference; not continuous scheduler coverage.')
