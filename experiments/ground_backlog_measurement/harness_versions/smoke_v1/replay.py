"""Enabled native GUI, fixed optical/camera replay, real SDK, original NumPy."""
import argparse,csv,hashlib,importlib.util,json,runpy,sys,threading,time
from dataclasses import asdict
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from qtpy.QtCore import QObject,QEventLoop,Qt,QTimer,Signal,Slot
from qtpy.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel
from hardware.sensor_frame import DeviceLayout,SensorSegment,SensorFrame
from hardware.walking_preflight import RuntimeBeamEvidence
from engine.device_quality_session import DeviceQualitySession
from engine.overground_session import OvergroundSession
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from ui.session_controller import SessionController,_GroundFrameInbox
from ui.views.execution_view import ExecutionView
from ui.ground_track import GroundChannelWidget
from ui.annotation_canvas import AnnotationCanvas
from camera.control_service import CameraControlService
from queue_probe import QueueProbe
from native_load import NativeLoad

spec=importlib.util.spec_from_file_location('frozen_replay',ROOT/'experiments/ground_throughput_diagnosis/enabled_replay.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class Source(old.OfflineWorker):
    def __init__(self,folder,**kwargs):
        QObject.__init__(self)
        self.folder=folder;self.cancel=threading.Event();self.reader=None;self.anchor_ns=None
        self.sdk_ready=threading.Event();self.arm_ready=threading.Event();self.arm_pause_ns=0;self.arrivals=[];self.delivered=[]
        self.meta=json.loads((folder/'report.json').read_text(encoding='utf-8'))['report_config_snapshot']
        d=self.meta['device'];g=d['layout'];self.layout=DeviceLayout(tuple(SensorSegment(**v) for v in g['segments']),tuple(g['invalid_bit_indices']));self.stream_id=d['stream_id']
        evidence=json.loads((folder/'acquisition_evidence.json').read_text(encoding='utf-8'));assert not evidence['issues']
        with np.load(folder/'raw_frames.npz') as data:
            first=int(np.searchsorted(data['sample_indices'],d['checked_sample_index']-3500));checked=int(np.searchsorted(data['sample_indices'],d['checked_sample_index']));end=checked+1+self.meta['raw_buffer']['total_received_frames']
            assert self.meta['raw_buffer']['raw_only_tail_frames']==0 and not self.meta['raw_buffer']['truncated']
            self.data={k:data[k][first:end].copy() for k in data.files}
        self.frame_meta=evidence['frames'][first:end];self.indices=self.data['sample_indices']
        self.offsets=self.data['received_ns']-self.data['received_ns'][0];self.original_start_ns=int(self.data['received_ns'][0])
        assert len(self.indices)==3501+self.meta['raw_buffer']['total_received_frames']
    @Slot()
    def start_capture(self):
        if self.reader:return
        self.layout_detected.emit(self.layout);self.device_state_changed.emit('streaming','Fixed original optical source')
        def read():
            if not self.sdk_ready.wait(30):self.arm_error='SDK startup timeout';return
            if self.cancel.wait(1):return
            self.anchor_ns=time.perf_counter_ns()
            for k,n in enumerate(self.indices):
                due=self.anchor_ns+int(self.offsets[k])
                if self.cancel.wait(max(0,(due-time.perf_counter_ns())/1e9)):return
                now=time.perf_counter_ns();m=self.frame_meta[k]
                frame=SensorFrame(m['stream_id'],self.layout,int(self.data['frame_indices'][k]),int(n),now,self.data['bits'][k].tobytes(),self.data['valid_bits'][k].tobytes(),self.data['wire'][k].tobytes(),int(self.data['dropped_frames_before'][k]),tuple(m['quality_flags']))
                self.delivered.append(frame);self.arrivals.append((now,due,int(n)))
                self.sensor_frame_received.emit(frame)
                if n==self.meta['device']['checked_sample_index']:
                    pause=time.perf_counter_ns()
                    if not self.arm_ready.wait(10):
                        self.arm_error='Arm/SDK readiness timeout';return
                    self.arm_pause_ns=time.perf_counter_ns()-pause;self.anchor_ns+=self.arm_pause_ns
            self.exhausted_ns=time.perf_counter_ns();self.exhausted.emit()
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()


def main(args):
    args.output.mkdir(parents=True,exist_ok=False)
    baseline=json.loads((ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
    assert all(sha(ROOT/name)==value for name,value in baseline.items())
    assert RuntimeBeamEvidence.__module__=='hardware.walking_preflight'
    renderer=HERE.parent/'beam_painter_state/baseline_renderer.py' if args.variant=='A' else ROOT/'experiments/runtime_single_frame_fusion/fixed_geometry_cache.py'
    spec=importlib.util.spec_from_file_location('chosen_renderer',renderer);cache=importlib.util.module_from_spec(spec);spec.loader.exec_module(cache);cache.install()
    app=QApplication([]);source=Source(args.input);meta=source.meta
    (args.output/'pid.json').write_text(json.dumps({'pid':__import__('os').getpid()}))
    cls=WalkingConfig if args.mode=='walk' else OvergroundRunningConfig
    cfg=cls(**{k:v for k,v in meta.items() if k in cls.__dataclass_fields__ and cls.__dataclass_fields__[k].init})
    common,batches,paints,sdk_errors=[],[],{},[]
    queue_probe=QueueProbe(int(source.indices[0]),args.probe=='P')
    native=NativeLoad(args.load,args.output);native.start()
    sdk={'start_success':False,'tracking_decisions':0,'nonzero_speeds':0,'stop_success':False}
    draws={'all':0,'valid':0,'disabled_calls':0,'smoke_screenshot':False};threads={'gui':threading.get_native_id()}
    original_init=CameraControlService.__init__
    def control_init(self,*a,**kw):
        original_init(self,*a,**kw)
        def result(method,code):
            if method=='tracking_start':
                sdk['start_success']=code==0
                if code==0:source.sdk_ready.set()
            if method=='tracking_stop':sdk['stop_success']=code==0
            if code<0:sdk_errors.append([method,code])
        def event(value):
            if value.get('event')=='tracking_decision' and value.get('reason')=='tracking':sdk['tracking_decisions']+=1
            if value.get('event')=='sdk_call' and value.get('method')=='set_speed' and any(value['args']):sdk['nonzero_speeds']+=1
        self.completed.connect(result);self.failed.connect(lambda text:sdk_errors.append(text));self.tracking_event.connect(event)
    CameraControlService.__init__=control_init
    original_draw=AnnotationCanvas._draw_live_pose
    def draw(self,painter,rect):
        overlay=self._live_pose[0];nodes=overlay['nodes'];draws['all']+=1
        valid=any(nodes[a]['valid'] and nodes[b]['valid'] for a,b in overlay['connections'])
        draws['valid']+=int(valid);draws['disabled_calls']+=int(not self.isEnabled())
        if valid and args.output.name.startswith('smoke') and not draws['smoke_screenshot']:
            draws['smoke_screenshot']=True;QTimer.singleShot(0,lambda:self.window().grab().save(str(args.output/'preview.png')))
        return original_draw(self,painter,rect)
    AnnotationCanvas._draw_live_pose=draw
    original_consume=_GroundFrameInbox._consume
    def consume(self,items):
        if items and 'consumer' not in threads:threads['consumer']=threading.get_native_id()
        return queue_probe.consume(self,items,original_consume)
    _GroundFrameInbox._consume=consume
    for target in (DeviceQualitySession,OvergroundSession):
        original_poll=target.poll
        def finite_poll(self,_original=original_poll):
            if getattr(source,'exhausted_ns',None) is None:return _original(self)
        target.poll=finite_poll
    controller=SessionController(worker_factory=lambda **kw:source)
    window=QWidget();window.setWindowTitle('IronJump queue measurement / '+args.load+' / '+args.mode+' / '+args.variant+' / '+args.probe);window.resize(1450,900);window.setStyleSheet('background:#0d121a;color:#e0e0e0;')
    layout=QVBoxLayout(window);banner=QLabel('Automated fixed-input replay; real SDK active');layout.addWidget(banner)
    body=QHBoxLayout();layout.addLayout(body);view=ExecutionView();body.addWidget(view,4);body.addWidget(view._ground_track,1)
    view.configure(cfg);view._camera_start_timer.stop();panel=view._camera_panel
    panel.setEnabled(True);panel.set_vision_enabled(True);panel._show_pose_action.setChecked(True);panel._chk_sdk_tracking.setChecked(True)
    for button in (view.btn_logi_camera,view.btn_tinyse_camera,view.btn_basic_camera):button.setEnabled(False)
    assert panel._ensure_control();panel._preview_active=True;panel._start_vision();panel._preview_timer.start()
    controller.device_state_changed.connect(view.on_device_state);controller.device_layout_changed.connect(view.on_device_layout)
    controller.walking_readiness_changed.connect(view.on_walking_readiness);controller.session_started.connect(view.on_session_started)
    controller.gait_snapshot.connect(view.on_gait_snapshot);controller.footprint_visual_frame.connect(view.on_footprint_visual_frame);controller.beam_quality_notice.connect(view.on_beam_quality_notice)
    expected={e['contact_id'] for e in json.loads((args.input/'report.json').read_text(encoding='utf-8'))['walking_summary' if args.mode=='walk' else 'running_summary']['event_publications'] if e['active']}
    original_paint=GroundChannelWidget.paintEvent
    def paint(widget,event):
        original_paint(widget,event)
        if widget is view._ground_track.channel and len(paints)<len(expected):
            for foot in widget._feet+widget.history:
                cid=foot.get('contact_id')
                if cid in expected and cid not in paints and foot.get('status')=='confirmed':paints[cid]=time.perf_counter_ns()
    GroundChannelWidget.paintEvent=paint
    status={};startup=[];armed=[];reports=[];errors=[];camera_stop=threading.Event();camera_stats={'decoded_frames':0};camera_thread=[]
    class Delivery(QObject):
        @Slot(dict)
        def ready(self,value):
            status.clear();status.update(value)
            if args.output.name.startswith('smoke') and len(startup)<4000:startup.append({'ready':value['ready'],'message':value['message'],'key':str(value.get('device_key')),'sdk':dict(sdk),'consumed':getattr(controller._frame_inbox,'last_consumed_sample',None),'host_ns':time.perf_counter_ns()})
        @Slot()
        def check(self):
            if armed:return
            if getattr(source,'arm_error',None):
                self.timeout();return
            if (status.get('ready') and sdk['start_success'] and getattr(controller._frame_inbox,'last_consumed_sample',-1)==meta['device']['checked_sample_index']):
                controller.start(acknowledge_quality=True,quality_key=status['device_key'])
        @Slot()
        def started(self):
            native.arm();armed.append(time.perf_counter_ns());source.arm_ready.set();(args.output/'armed.json').write_text(json.dumps({'host_ns':armed[0]}))
        @Slot()
        def exhausted(self):
            def settle():
                if getattr(controller._frame_inbox,'last_consumed_sample',-1)<int(source.indices[-1]):QTimer.singleShot(20,settle);return
                QTimer.singleShot(200,lambda:controller.stop('manual'))
            settle()
        @Slot(object)
        def finished(self,report):native.finish();reports.append(report);app.quit()
        @Slot()
        def timeout(self):
            if errors:return
            timer.stop();errors.append('watchdog_timeout')
            (args.output/'failure_state.json').write_text(json.dumps({'startup':startup,'status':status,'sdk':sdk,'sdk_errors':sdk_errors,'consumed':getattr(controller._frame_inbox,'last_consumed_sample',None),'checked':meta['device']['checked_sample_index'],'source_count':len(source.delivered)},default=str),encoding='utf-8')
            if controller.is_running:controller.stop('manual')
            else:controller.discard();app.quit()
    delivery=Delivery();controller.walking_readiness_changed.connect(delivery.ready);controller.session_started.connect(delivery.started)
    controller.session_finished.connect(delivery.finished);source.exhausted.connect(delivery.exhausted,Qt.QueuedConnection)
    controller.prepare(cfg);engine=controller._engine;quality=controller._quality
    queue_probe.start(controller._frame_inbox)
    timer=QTimer(window);timer.setInterval(5);timer.timeout.connect(delivery.check);timer.start()
    def video():
        if source.anchor_ns is None:QTimer.singleShot(10,video);return
        thread=threading.Thread(target=old.replay_camera,args=(panel,source,camera_stop,camera_stats),daemon=True);camera_thread.append(thread);thread.start()
    QTimer.singleShot(0,video);QTimer.singleShot(90000,delivery.timeout)
    window.show();app.exec();camera_stop.set();queue_probe.close()
    for thread in camera_thread:thread.join(2)
    if controller._thread:controller.discard()
    panel.shutdown();control=panel._closing_control
    if control is not None:
        loop=QEventLoop();control.closed.connect(loop.quit);QTimer.singleShot(6000,loop.quit);loop.exec()
    if panel._closing_control is not None or panel._control_stop_failed:errors.append('SDK shutdown not confirmed')
    native_result=native.close()
    assert reports and not errors,(len(reports),errors)
    common=[row[:3] for row in queue_probe.common]
    report=asdict(reports[0]);report.pop('export_frames',None);report.pop('export_timestamps',None)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
    runtime=quality._runtime;window_hash=hashlib.sha256()
    for bits,changes in runtime._window:window_hash.update(bits.tobytes());window_hash.update(changes.tobytes())
    state={'quality':quality.snapshot(),'runtime_counts':runtime._counts.tolist(),'runtime_transitions':runtime._transitions.tolist(),'runtime_healthy':runtime.healthy_samples,'runtime_window_sha256':window_hash.hexdigest(),'audit':digest(engine.overground.processor.event_audit),'timeline':digest(list(engine.overground.processor.timeline)),'mirror_events':engine.overground._frame_filter.mirror_guard.events,'raw_archive_sha256':hashlib.sha256(b''.join(engine.overground.frames)).hexdigest()}
    np.savez_compressed(args.output/'raw_frames.npz',**{k:np.array([getattr(f,attr) for f in source.delivered]) for k,attr in [('sample_indices','sample_index'),('frame_indices','frame_index'),('received_ns','received_monotonic_ns'),('dropped_frames_before','dropped_frames_before')]},bits=np.array([np.frombuffer(f.contact_bits,np.uint8) for f in source.delivered]),wire=np.array([np.frombuffer(f.wire_payload,np.uint8) for f in source.delivered]),valid_bits=np.array([np.frombuffer(f.valid_bits,np.uint8) for f in source.delivered]))
    assert sdk['start_success'] and not sdk_errors and sdk['tracking_decisions'] and sdk['nonzero_speeds'] and draws['valid']
    assert panel.isEnabled() and panel._show_pose_action.isChecked() and not draws['disabled_calls']
    result={'mode':args.mode,'load':args.load,'variant':args.variant,'probe':args.probe,'queue_common':queue_probe.common,'queue_samples':queue_probe.samples,'native':native_result,'common':common,'batches':batches,'paints':paints,'arrivals':source.arrivals,'sdk':sdk,'sdk_errors':sdk_errors,'pose_draws':draws,'camera':camera_stats,'state':state,'baseline_files_exact':len(baseline),'baseline_hashes':baseline,'renderer_sha256':sha(renderer),'sources':{p.name:sha(p) for p in (HERE/'replay.py',HERE/'queue_probe.py',HERE/'native_load.py')},'source_indices':[int(source.indices[0]),int(source.indices[-1])],'checked':meta['device']['checked_sample_index'],'threads':threads,'armed_ns':armed[0],'anchor_ns':source.anchor_ns,'arm_pause_ns':source.arm_pause_ns,'delivered_metadata_sha256':digest([[f.stream_id,list(f.quality_flags),f.dropped_frames_before] for f in source.delivered]),'errors':errors,'finite_EOF_poll_exemption':True,'qt_platform':app.platformName()}
    (args.output/'measurement.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'mode':args.mode,'variant':args.variant,'probe':args.probe,'SDK':sdk,'draws':draws,'camera':camera_stats}),flush=True)
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--mode',choices=('walk','run'),required=True);parser.add_argument('--variant',choices=('A','B'),required=True);parser.add_argument('--probe',choices=('L','P'),required=True);parser.add_argument('--load',choices=('fixed','capture','record'),required=True)
    result=main(parser.parse_args());raise SystemExit(result)
