"""Separate application return from bounded observer-only tail finalization."""
import copy
from functools import wraps
from pathlib import Path
import sys
import threading
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'gil_observation_termination'))
from snapshot import FrozenAudit


class RetainedAudit(FrozenAudit):
    def __init__(self):
        super().__init__();self.retained_services={}

    def install(self):
        super().install()
        from vision.service import FootVisionService
        original=FootVisionService.__init__;audit=self
        @wraps(original)
        def init(service,*args,**kwargs):
            value=original(service,*args,**kwargs)
            audit.retained_services[audit.tags[service]]=service
            return value
        FootVisionService.__init__=init


def prefix_equal(first,last):
    if first['pid']!=last['pid'] or first['event_sequence']>last['event_sequence']:return False
    for name,rows in first['rows'].items():
        if last['rows'].get(name,[])[:len(rows)]!=rows:return False
    return True


def finalize(audit,write,timeout_s,application_outcome):
    first=audit.finish()
    write('application_return.json',dict(application_outcome=application_outcome,snapshot=first))
    # This phase runs after the original application function has returned.
    # It does not call stop() again, change its timeout, or hold the event lock.
    deadline=time.monotonic()+timeout_s;joins=[]
    for tag,service in audit.retained_services.items():
        worker=service._thread;begin=time.perf_counter_ns()
        before=None if worker is None else worker.is_alive()
        if worker is threading.current_thread():raise RuntimeError('Cannot join recorder thread')
        if worker is not None:worker.join(max(0,deadline-time.monotonic()))
        after=None if worker is None else worker.is_alive()
        joins.append(dict(service=tag,tid=None if worker is None else worker.native_id,begin_ns=begin,end_ns=time.perf_counter_ns(),alive_before=before,alive_after=after))
    last=audit.finish();write('observer_tail.json',last)
    checks=dict(application_outcome_known=application_outcome['success'] is True,
                original_prefix_preserved=prefix_equal(first,last),
                no_join_timeout=all(x['alive_after'] is not True for x in joins),
                final_model_checks=all(last['model_end_checks'].values()))
    result=dict(schema=1,checks=checks,metadata_finalization_pass=all(checks.values()),joins=joins,
                application_return_model_checks=copy.deepcopy(first['model_end_checks']),
                application_return_model_confirmed=all(first['model_end_checks'].values()),
                observer_tail_model_checks=copy.deepcopy(last['model_end_checks']),
                actual_load_disturbance_pass=False,field_attribution_ready=False,
                scope='Additional observer lifetime after original application return, outside the CPU/cycles ROI. An unconfirmed original return is retained; a later success never rewrites it.')
    write('finalization.json',result)
    return result
