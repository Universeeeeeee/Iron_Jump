"""Require observed GUI launch context; never silently normalize process priority."""
def check_context(record,expected_session=None):
    if record['session_id']==0:raise ValueError('Noninteractive session')
    if expected_session is not None and record['session_id']!=expected_session:raise ValueError('Session changed')
    if record['priority_class']!=16384:raise ValueError('Unexpected priority; do not change it')
    if record['qpa']!='windows':raise ValueError('Wrong Qt backend')
    for name in ('process','thread'):
        v=record[name]
        if not v['success'] or v['version']!=1 or v['control_mask']&1 or v['state_mask']&1:raise ValueError('Unexpected initial QoS')
    return True
