import copy
import json
import sys
from types import ModuleType,SimpleNamespace as S
import unittest
from unittest.mock import patch
from workload import Audit,metadata,packet
from verify import check_workload


def fixture():
    meta=dict(frame_index=7,sample_time_s=50.,callback_time_s=112.99,decoded_at_s=112.9901,clock_sync_status='ready',clock_sync_uncertainty_ms=.1,camera_clock_epoch=1)
    info=dict(frame_timestamp_s=112.99,inference_start_s=113.,inference_end_s=113.02,has_pose=True,error=None,metadata=copy.deepcopy(meta))
    p=dict(generation=1,barrier_sequence=0,barrier=None,update=dict(status='pose',inference=copy.deepcopy(info)))
    a=Audit();rows=a.rows
    rows['service_submit_calls']=[dict(service=0,tid=30,begin_ns=112990000000,end_ns=112990100000,captured_at_s=112.99,metadata=copy.deepcopy(meta))]
    rows['inferences']=[dict(service=0,tid=20,observed_ns=113021000000,record=copy.deepcopy(info))]
    rows['adapter_calls']=[dict(tid=20,adapter=5,begin_ns=113001000000,end_ns=113019000000,timestamp_ms=112990,shape=[360,640,3],dtype='uint8',has_pose=True,error=None)]
    rows['model_open']=[dict(tid=20,adapter=5,begin_ns=100300000000,end_ns=100400000000,is_open=True,error=None)]
    rows['model_close']=[dict(tid=20,adapter=5,begin_ns=120000000000,end_ns=120010000000,is_open=False,error=None)]
    rows['service_status']=[dict(service=0,status='ready',tid=20),dict(service=0,status='stopped',tid=20)]
    rows['relay_packets']=[dict(tid=10,observed_ns=113022000000,packet=copy.deepcopy(p))]
    rows['sdk_events']=[dict(control=0,tid=10,observed_ns=113026000000,data=dict(event='pose_input',received_at_s=113.025,packet=copy.deepcopy(p))),dict(control=0,tid=10,observed_ns=113027000000,data=dict(event='tracking_decision',reason='tracking')),dict(control=0,tid=10,observed_ns=113029000000,data=dict(event='sdk_call',method='set_speed',args=[1,2],started_at=113.027,returned_at=113.028,result=None,error=None))]
    rows['control_lifecycle']=[dict(tid=10,control=0,event='started',pid=2,observed_ns=101000000000),dict(tid=10,control=0,event='finished',pid=2,exit_code=0,observed_ns=121000000000)]
    before=[dict(pid=1 if t!=60 else 2,tid=t,role='sdk' if t==60 else 'gui',active=True,creation_100ns=100+t,cycles=100,user_100ns=0,kernel_100ns=0) for t in (10,20,30,40,50,60)]
    w=dict(schema=1,pid=1,rows=rows,service_count=1,running_services=[],replay_serialized=True)
    m=dict(threads=dict(gui=10,consumer=40,reader=50),sdk=dict(tracking_decisions=1,nonzero_speeds=1))
    c=dict(target_pid=1,armed=dict(pid=1,host_ns=100000000000),before=before,after=copy.deepcopy(before))
    return w,m,c


class LinkTests(unittest.TestCase):
    def bad(self,change,gate):
        w,m,c=fixture();change(w,m,c);r=check_workload(w,m,c);self.assertFalse(r['checks'][gate]);self.assertFalse(r['observability_pass'])
    def test_valid_independent_links(self):
        w,m,c=fixture();r=check_workload(w,m,c);self.assertTrue(r['observability_pass'],r);self.assertEqual(r['ROI_inference_identities'],[[1,7]])
    def test_missing_inference(self):
        self.bad(lambda w,m,c:w['rows']['inferences'].clear(),'all_adapter_inference_submit_links')
    def test_duplicate_adapter_call(self):
        self.bad(lambda w,m,c:w['rows']['adapter_calls'].append(copy.deepcopy(w['rows']['adapter_calls'][0])),'all_adapter_inference_submit_links')
    def test_wrong_frame(self):
        self.bad(lambda w,m,c:w['rows']['inferences'][0]['record']['metadata'].__setitem__('frame_index',8),'all_adapter_inference_submit_links')
    def test_wrong_camera_epoch(self):
        self.bad(lambda w,m,c:w['rows']['inferences'][0]['record']['metadata'].__setitem__('camera_clock_epoch',2),'all_adapter_inference_submit_links')
    def test_adapter_outside_inference(self):
        self.bad(lambda w,m,c:w['rows']['adapter_calls'][0].__setitem__('end_ns',114000000000),'all_adapter_inference_submit_links')
    def test_model_not_closed(self):
        self.bad(lambda w,m,c:w['rows']['model_close'][0].__setitem__('adapter',9),'model_lifetimes')
    def test_callback_fault(self):
        self.bad(lambda w,m,c:w['rows']['callback_errors'].append(dict(error='fault')),'no_callback_faults')
    def test_running_service(self):
        self.bad(lambda w,m,c:w['running_services'].append(0),'capture_identity')
    def test_unknown_vision_lifetime(self):
        self.bad(lambda w,m,c:c['before'].__delitem__(1),'inference_ROI_lifetimes')
    def test_recycled_native_tid(self):
        self.bad(lambda w,m,c:c['after'][1].__setitem__('creation_100ns',999),'native_handle_identity')
    def test_sdk_same_pid_as_gui(self):
        self.bad(lambda w,m,c:c['before'][-1].__setitem__('pid',1),'separate_SDK_PID')
    def test_wrong_control_identity(self):
        self.bad(lambda w,m,c:w['rows']['sdk_events'][0].__setitem__('control',9),'SDK_control_identity')
    def test_missing_sdk_packet(self):
        self.bad(lambda w,m,c:w['rows']['sdk_events'].pop(0),'all_relay_SDK_metadata_links')
    def test_extra_relay_packet(self):
        self.bad(lambda w,m,c:w['rows']['relay_packets'].append(copy.deepcopy(w['rows']['relay_packets'][0])),'all_relay_SDK_metadata_links')
    def test_sdk_mismatched_inference(self):
        self.bad(lambda w,m,c:w['rows']['sdk_events'][0]['data']['packet']['update']['inference'].__setitem__('inference_end_s',113.03),'all_relay_SDK_metadata_links')
    def test_child_clock_contradiction(self):
        self.bad(lambda w,m,c:w['rows']['sdk_events'][0]['data'].__setitem__('received_at_s',200.),'independent_child_clock_bracket')
    def test_wrapper_return_contract(self):
        self.bad(lambda w,m,c:w['rows']['sdk_events'][-1]['data'].__setitem__('result',0),'SDK_calls_successful')
    def test_sdk_aggregate_mismatch(self):
        self.bad(lambda w,m,c:m['sdk'].__setitem__('nonzero_speeds',2),'SDK_aggregate_counts')
    def test_gui_event_from_wrong_thread(self):
        self.bad(lambda w,m,c:w['rows']['relay_packets'][0].__setitem__('tid',20),'GUI_roles')


class Hook:
    def __init__(self):self.callbacks=[]
    def connect(self,fn):self.callbacks.append(fn)
    def emit(self,*args):
        for fn in self.callbacks:fn(*args)


def fake_classes():
    token=object()
    class Service:
        def __init__(self,*args,**kw):
            self.received=(args,kw);self.pose_inference_ready=Hook();self.status_changed=Hook();self.is_running=False
        def submit_frame(self,*args,**kw):self.last=(args,kw);return token
    class Adapter:
        def __init__(self):self.is_open=False;self.error=None
        def open(self):self.is_open=True;return token
        def close(self):self.is_open=False;return token
        def infer_bgr(self,*args):
            self.last=args
            if self.error:raise self.error
            return token
    class Control:
        def __init__(self):
            self._process=S(started=Hook(),finished=Hook(),processId=lambda:2);self.completed=Hook();self.tracking_event=Hook()
        def _read(self):return token
        def _send_pose(self):return token
        def request(self,*args):self.last=args;return token
    class Relay:
        def packet(self,generation):return self.value
    modules={name:ModuleType(name) for name in ('vision','vision.service','vision.mediapipe_pose','camera','camera.control_service','camera.pose_transport')}
    modules['vision'].__path__=[];modules['camera'].__path__=[]
    modules['vision.service'].FootVisionService=Service;modules['vision.mediapipe_pose'].MediaPipePoseAdapter=Adapter
    modules['camera.control_service'].CameraControlService=Control;modules['camera.pose_transport'].PoseRelay=Relay
    return modules,Service,Adapter,Control,Relay,token


class HookTests(unittest.TestCase):
    def test_forward_same_arguments_results_and_exceptions(self):
        modules,Service,Adapter,Control,Relay,token=fake_classes()
        with patch.dict(sys.modules,modules):
            a=Audit();a.install();s=Service('config',flag=True);self.assertEqual(s.received,(('config',),dict(flag=True)))
            frame=S(shape=(360,640,3),dtype='uint8');meta=S(frame_index=1,sample_time_s=2.,callback_time_s=3.,decoded_at_s=3.,clock_sync_status='ready',clock_sync_uncertainty_ms=.1,camera_clock_epoch=0)
            self.assertIs(s.submit_frame(frame,3.,metadata=meta),token);self.assertIs(s.last[0][0],frame);self.assertIs(s.last[1]['metadata'],meta)
            adapter=Adapter();self.assertIs(adapter.open(),token);self.assertIs(adapter.infer_bgr(frame,3000),token);self.assertIs(adapter.last[0],frame)
            fault=ValueError('injected');adapter.error=fault
            with self.assertRaises(ValueError) as caught:adapter.infer_bgr(frame,3001)
            self.assertIs(caught.exception,fault);self.assertEqual(a.rows['adapter_calls'][-1]['error'],'ValueError');self.assertIs(adapter.close(),token)
            control=Control();control._process.started.emit();self.assertIs(control._read(),token);self.assertIs(control._send_pose(),token);self.assertIs(control.request('tracking_start',1),token)
            self.assertEqual(control.last,('tracking_start',1));self.assertEqual(a.rows['control_lifecycle'][0]['pid'],2)
    def test_packet_projection_drops_coordinates_and_preserves_input(self):
        w,m,c=fixture();info=w['rows']['inferences'][0]['record'];r=dict(frame_timestamp_s=info['frame_timestamp_s'],inference_start_timestamp_s=info['inference_start_s'],inference_end_timestamp_s=info['inference_end_s'],pose=dict(landmarks=[[123,456]]),error=None,frame_metadata=info['metadata'])
        value=dict(generation=1,barrier_sequence=0,barrier=None,update=dict(status='pose',inference=r));before=copy.deepcopy(value)
        projected=packet(value);self.assertEqual(value,before);self.assertNotIn('landmarks',json.dumps(projected));self.assertTrue(projected['update']['inference']['has_pose'])
    def test_unknown_sdk_event_is_retained_as_fault(self):
        a=Audit();a.sdk(0,dict(event='unexpected'));self.assertTrue(a.rows['callback_errors'])
    def test_missing_inference_metadata_is_retained(self):
        a=Audit();value=S(frame_timestamp_s=1.,inference_start_timestamp_s=2.,inference_end_timestamp_s=3.,pose=None,error=None,frame_metadata=None)
        a.on_inference(0,value);self.assertIsNone(a.rows['inferences'][0]['record']['metadata'])


if __name__=='__main__':unittest.main()
