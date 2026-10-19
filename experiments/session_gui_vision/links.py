"""Parent SDK completion witness releases source only after an actual protocol reply."""
import os
import time

sdk_patch_installed=False
client=None
sdk=dict(start_success=False,stop_success=False,ready_events=[],errors=[],tracking_decisions=0,nonzero_speeds=0)

def bind_client(value):
    global client
    client=value
    if sdk['ready_events']:client.sdk_ready(sdk['ready_events'][0])

def attach(control):
    def completed(method,code):
        if code<0:sdk['errors'].append(dict(method=method,code=code))
        if method=='tracking_start' and code==0:
            info=dict(method=method,code=code,sdk_pid=int(control._process.processId()),gui_pid=os.getpid(),observed_ns=time.perf_counter_ns())
            sdk['start_success']=True;sdk['ready_events'].append(info)
            if client is not None:client.sdk_ready(info)
        elif method=='tracking_stop' and code==0:sdk['stop_success']=True
    def event(value):
        if value.get('event')=='tracking_decision' and value.get('reason')=='tracking':sdk['tracking_decisions']+=1
        if value.get('event')=='sdk_call' and value.get('method')=='set_speed' and any(value['args']):sdk['nonzero_speeds']+=1
    control.completed.connect(completed);control.tracking_event.connect(event)
    control.failed.connect(lambda text:sdk['errors'].append(text))
