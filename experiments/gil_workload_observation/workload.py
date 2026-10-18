"""Process-local metadata beside the unchanged replay. No pixels or pose coordinates."""
import os
import sys
import threading
import time
import weakref


def metadata(value):
    if value is None:return None
    names=('frame_index','sample_time_s','callback_time_s','decoded_at_s','clock_sync_status','clock_sync_uncertainty_ms','camera_clock_epoch')
    return {n:getattr(value,n) for n in names}


def inference(value):
    if value is None:return None
    return dict(frame_timestamp_s=value.frame_timestamp_s,
                inference_start_s=value.inference_start_timestamp_s,
                inference_end_s=value.inference_end_timestamp_s,
                has_pose=value.pose is not None,error=value.error,
                metadata=metadata(value.frame_metadata))


def packet(value):
    def update(u):
        if u is None:return None
        r=u['inference']
        info=None if r is None else dict(frame_timestamp_s=r['frame_timestamp_s'],inference_start_s=r['inference_start_timestamp_s'],inference_end_s=r['inference_end_timestamp_s'],has_pose=r['pose'] is not None,error=r['error'],metadata=r['frame_metadata'])
        return dict(status=u['status'],inference=info)
    return dict(generation=value['generation'],barrier_sequence=value['barrier_sequence'],
                barrier=update(value['barrier']),update=update(value['update']))


class Audit:
    def __init__(self):
        self.pid=os.getpid();self.services=[];self.tags=weakref.WeakKeyDictionary();self.installed=False
        self.rows={n:[] for n in ('service_submit_calls','inferences','service_status','adapter_calls','model_open','model_close','gui_io','relay_packets','sdk_events','control_lifecycle','tracking_requests','callback_errors')}

    def event(self,table,**values):
        self.rows[table].append(dict(observed_ns=time.perf_counter_ns(),tid=threading.get_native_id(),**values))

    def on_inference(self,tag,value):
        try:self.event('inferences',service=tag,record=inference(value))
        except Exception as exc:self.event('callback_errors',where='inference',error=repr(exc))

    def sdk(self,tag,value):
        try:
            kind=value['event']
            if kind=='pose_input':
                data=dict(event=kind,received_at_s=value['received_at'],packet=packet(value['packet']))
            elif kind=='sdk_call':
                data={n:value[n] for n in ('event','method','args','started_at','returned_at')}
                data.update(result=value.get('result'),error=value.get('error'))
            elif kind=='tracking_decision':
                data={n:value[n] for n in ('event','generation','pitch','pan','captured_at','reason')}
            else:
                self.event('callback_errors',where='sdk_event',error='Unknown event: '+str(kind));return
            self.event('sdk_events',control=tag,data=data)
        except Exception as exc:self.event('callback_errors',where='sdk_event',error=repr(exc))

    def install(self):
        assert not self.installed;self.installed=True
        from vision.service import FootVisionService
        from vision.mediapipe_pose import MediaPipePoseAdapter
        from camera.control_service import CameraControlService
        from camera.pose_transport import PoseRelay
        audit=self
        original=FootVisionService.__init__
        def service_init(service,*args,**kwargs):
            result=original(service,*args,**kwargs)
            tag=len(audit.services);audit.services.append(weakref.ref(service));audit.tags[service]=tag
            service.pose_inference_ready.connect(lambda record:audit.on_inference(tag,record))
            service.status_changed.connect(lambda status:audit.event('service_status',service=tag,status=status))
            return result
        FootVisionService.__init__=service_init
        original_submit=FootVisionService.submit_frame
        def submit(service,frame,captured_at_s,**kwargs):
            before=time.perf_counter_ns()
            result=original_submit(service,frame,captured_at_s,**kwargs)
            audit.event('service_submit_calls',service=audit.tags[service],begin_ns=before,end_ns=time.perf_counter_ns(),captured_at_s=captured_at_s,metadata=metadata(kwargs.get('metadata')))
            return result
        FootVisionService.submit_frame=submit
        original_infer=MediaPipePoseAdapter.infer_bgr
        def infer(adapter,frame,timestamp_ms):
            before=time.perf_counter_ns();result=None
            try:
                result=original_infer(adapter,frame,timestamp_ms);return result
            finally:
                error=sys.exc_info()[0]
                audit.event('adapter_calls',adapter=id(adapter),begin_ns=before,end_ns=time.perf_counter_ns(),timestamp_ms=timestamp_ms,shape=list(frame.shape),dtype=str(frame.dtype),has_pose=result is not None,error=None if error is None else error.__name__)
        MediaPipePoseAdapter.infer_bgr=infer
        def adapter_span(name,table):
            method=getattr(MediaPipePoseAdapter,name)
            def wrapped(adapter,*args,**kwargs):
                before=time.perf_counter_ns()
                try:return method(adapter,*args,**kwargs)
                finally:
                    error=sys.exc_info()[0]
                    audit.event(table,adapter=id(adapter),begin_ns=before,end_ns=time.perf_counter_ns(),is_open=adapter.is_open,error=None if error is None else error.__name__)
            setattr(MediaPipePoseAdapter,name,wrapped)
        adapter_span('open','model_open');adapter_span('close','model_close')
        original_control=CameraControlService.__init__;serial=[0]
        def control_init(control,*args,**kwargs):
            result=original_control(control,*args,**kwargs);tag=serial[0];serial[0]+=1;control._workload_observation_tag=tag
            child=[None]
            def started():
                child[0]=int(control._process.processId());audit.event('control_lifecycle',control=tag,event='started',pid=child[0])
            control._process.started.connect(started)
            control._process.finished.connect(lambda code,status:audit.event('control_lifecycle',control=tag,event='finished',pid=child[0],exit_code=code,exit_status=str(status)))
            control.completed.connect(lambda method,code:audit.event('control_lifecycle',control=tag,event='completed',pid=child[0],method=method,result=code))
            control.tracking_event.connect(lambda value:audit.sdk(tag,value))
            return result
        CameraControlService.__init__=control_init
        for name in ('_read','_send_pose'):
            method=getattr(CameraControlService,name)
            def timed(control,*args,_method=method,_name=name,**kwargs):
                before=time.perf_counter_ns()
                try:return _method(control,*args,**kwargs)
                finally:
                    error=sys.exc_info()[0]
                    audit.event('gui_io',control=control._workload_observation_tag,method=_name,begin_ns=before,end_ns=time.perf_counter_ns(),error=None if error is None else error.__name__)
            setattr(CameraControlService,name,timed)
        original_request=CameraControlService.request
        def request(control,method,*args):
            if method in ('tracking_start','tracking_stop'):
                audit.event('tracking_requests',control=control._workload_observation_tag,method=method,args=list(args))
            return original_request(control,method,*args)
        CameraControlService.request=request
        original_packet=PoseRelay.packet
        def relay(relay,generation):
            result=original_packet(relay,generation)
            if result is not None:audit.event('relay_packets',packet=packet(result))
            return result
        PoseRelay.packet=relay

    def finish(self):
        running=[]
        for tag,reference in enumerate(self.services):
            service=reference()
            if service is not None and service.is_running:running.append(tag)
        return dict(schema=1,pid=self.pid,rows=self.rows,service_count=len(self.services),running_services=running,
                    scope='All common metadata hooks remain ON in both fresh-process cases. No inference policy, input selection, queue, filter, Processor, thread structure or painting algorithm changed. Observer disturbance unqualified.',
                    actual_load_disturbance_pass=False,field_attribution_ready=False)
