"""Native account deltas retain enclosing clock bounds; never compute waiting shares."""
def interval(a,b):
    x,y=a['value'],b['value']
    assert a['valid'] and b['valid'] and a['capture_end_ns']<=b['capture_begin_ns']
    assert (x['pid'],x['tid'])==(y['pid'],y['tid'])
    out={}
    for role in ('process','thread'):
        p,q=x[role],y[role];assert p['creation_100ns']==q['creation_100ns']
        assert all(q[k]>=p[k] for k in ('user_100ns','kernel_100ns','cycles'))
        out[role]=dict(user_cpu_ms=(q['user_100ns']-p['user_100ns'])/10000,kernel_cpu_ms=(q['kernel_100ns']-p['kernel_100ns'])/10000,cpu_ms=(q['user_100ns']+q['kernel_100ns']-p['user_100ns']-p['kernel_100ns'])/10000,cycles=q['cycles']-p['cycles'])
    assert out['process']['cpu_ms']+50>=out['thread']['cpu_ms']
    out.update(wall_ns_bounds=[y['begin_ns']-x['end_ns'],y['end_ns']-x['begin_ns']],named_thread_containment_tolerance_ms=50,
        scope='Enclosing account interval, including observer and concurrent process work. Thread is caller only; native workers are in process. No waiting percentage orGHz.')
    return out
