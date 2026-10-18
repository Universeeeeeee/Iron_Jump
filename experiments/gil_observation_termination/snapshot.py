"""New recorder candidate. Old source/plans and failed observations stay untouched."""
import copy
from functools import wraps
from pathlib import Path
import sys
import threading
import time

OLD=Path(__file__).resolve().parents[1]/'gil_workload_observation'
sys.path.insert(0,str(OLD))
from workload import Audit


class FrozenAudit(Audit):
    def __init__(self):
        super().__init__()
        self.rows['model_close_enter']=[]
        self._event_lock=threading.Lock();self._sequence=0

    def event(self,table,**values):
        observed=time.perf_counter_ns();tid=threading.get_native_id()
        values=copy.deepcopy(values)
        with self._event_lock:
            self._sequence+=1
            self.rows[table].append(dict(observed_ns=observed,tid=tid,event_sequence=self._sequence,commit_ns=time.perf_counter_ns(),**values))

    def close_entry(self,method):
        @wraps(method)
        def wrapped(adapter,*args,**kwargs):
            self.event('model_close_enter',adapter=id(adapter),begin_ns=time.perf_counter_ns())
            return method(adapter,*args,**kwargs)
        return wrapped

    def install(self):
        super().install()
        from vision.mediapipe_pose import MediaPipePoseAdapter
        # The old span wrapper records return/error. This adds entry, without
        # changing the original method, timeout or service-thread policy.
        MediaPipePoseAdapter.close=self.close_entry(MediaPipePoseAdapter.close)

    def finish(self):
        requested=time.perf_counter_ns()
        with self._event_lock:
            begin=time.perf_counter_ns();states=[]
            for tag,reference in enumerate(self.services):
                service=reference();before=time.perf_counter_ns()
                alive=None if service is None else bool(service.is_running)
                states.append(dict(service=tag,begin_ns=before,end_ns=time.perf_counter_ns(),alive=alive))
            # Both containers and nested payloads must belong to this snapshot.
            rows=copy.deepcopy(self.rows);sequence=self._sequence;end=time.perf_counter_ns()
        result=dict(schema=2,pid=self.pid,rows=rows,service_count=len(states),
                    running_services=[s['service'] for s in states if s['alive'] is True],
                    service_liveness_reads=states,event_sequence=sequence,
                    snapshot=dict(requested_ns=requested,locked_begin_ns=begin,locked_end_ns=end),
                    scope='Frozen committed event prefix; liveness reads have separate bounds. No globally atomic OS/native-pool state or observer-overhead qualification.',
                    actual_load_disturbance_pass=False,field_attribution_ready=False)
        result['model_end_checks']=model_end_checks(result)
        return result


def model_end_checks(snapshot):
    rows=snapshot['rows'];sequences=sorted(x['event_sequence'] for group in rows.values() for x in group)
    # This candidate qualifies only the single-service topology used by the
    # frozen replay. Ambiguous/multiple model instances remain unqualified.
    opens=rows['model_open'];enters=rows['model_close_enter'];closes=rows['model_close'];states=snapshot['service_liveness_reads']
    checks=dict(single_service=snapshot['service_count']==len(states)==1,
                committed_prefix=sequences==list(range(1,snapshot['event_sequence']+1)),
                service_exited=len(states)==1 and states[0]['alive'] is False,
                service_markers=all(any(x['service']==s['service'] and x['status']=='ready' for x in rows['service_status']) and any(x['service']==s['service'] and x['status']=='stopped' for x in rows['service_status']) for s in states),
                one_model=len(opens)==len(enters)==len(closes)==1,
                no_callback_faults=not rows['callback_errors'])
    if checks['one_model']:
        o,e,c=opens[0],enters[0],closes[0]
        checks['model_identity']=o['adapter']==e['adapter']==c['adapter'] and o['tid']==e['tid']==c['tid']
        checks['close_return_confirmed']=(o['error'] is None and c['error'] is None and o['is_open'] is True and c['is_open'] is False and o['event_sequence']<e['event_sequence']<c['event_sequence'] and o['end_ns']<=e['begin_ns']<=c['begin_ns']<=c['end_ns'])
    else:checks.update(model_identity=False,close_return_confirmed=False)
    return checks
