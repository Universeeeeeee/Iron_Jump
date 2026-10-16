"""Single production USB path and production preview; no replay or renderer install."""
import argparse,hashlib,json,os,sys,threading,time,traceback
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
from qtpy.QtCore import QObject,QEventLoop,QTimer,Qt,Slot
from qtpy.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from ui.session_controller import SessionController,_GroundFrameInbox
from hardware.usb_worker import UsbWorker
from ui.views.execution_view import ExecutionView
from ui.embedded_camera_panel import EmbeddedCameraPanel
from ui.annotation_canvas import AnnotationCanvas
from ui.ground_track import GroundChannelWidget
from camera.control_service import CameraControlService
from queue_probe import QueueProbe

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def native_stats(panel):
    c=panel._capture._capture
    s=c.stats();return {k:getattr(s,k) for k,_ in s._fields_}
def readers():return [{'ident':t.native_id,'name':t.name} for t in threading.enumerate() if t.name=='CyUsbInterfaceReader']

class Run(QObject):
    def __init__(self,args,app):
        super().__init__();self.args=args;self.app=app;self.probe=None;self.phase=None;self.status={};self.completed=[];self.errors=[];self.events=[];self.refs=None;self.started=False
        self.process_start_ns=time.perf_counter_ns();self.gui_tid=threading.get_native_id();self.consumer_tid=None
        self.visual={'renders':0,'pose_draw_calls':0,'valid_pose_draws':0,'valid_nodes_drawn':0,'disabled_calls':0};self.first_render_ns=None
        self.sdk={'starts':0,'stops':0,'nonzero_speeds':0};self.sdk_reasons=Counter();self.sdk_errors=[]
        original_consume=_GroundFrameInbox._consume
        def consume(inbox,items):
            if items and self.probe is None:
                first=next((v for issue,v in items if not issue),None)
                if first is not None:
                    self.probe=QueueProbe(first.sample_index,True);self.probe.start(inbox);self.consumer_tid=threading.get_native_id()
            if self.probe:return self.probe.consume(inbox,items,original_consume)
            return original_consume(inbox,items)
        _GroundFrameInbox._consume=consume
        original_render=EmbeddedCameraPanel._render_frame
        def render(panel,frame):
            self.visual['renders']+=1
            if self.first_render_ns is None:self.first_render_ns=time.perf_counter_ns()
            return original_render(panel,frame)
        EmbeddedCameraPanel._render_frame=render
        original_draw=AnnotationCanvas._draw_live_pose
        def draw(canvas,painter,rect):
            overlay=canvas._live_pose[0];nodes=overlay['nodes'];self.visual['pose_draw_calls']+=1
            self.visual['valid_pose_draws']+=int(any(nodes[a]['valid'] and nodes[b]['valid'] for a,b in overlay['connections']))
            self.visual['valid_nodes_drawn']+=sum(n['valid'] for n in nodes.values());self.visual['disabled_calls']+=int(not canvas.isEnabled())
            return original_draw(canvas,painter,rect)
        AnnotationCanvas._draw_live_pose=draw
        original_control=CameraControlService.__init__
        def control_init(control,*a,**kw):
            original_control(control,*a,**kw)
            def result(method,code):
                if code<0:self.sdk_errors.append([method,code])
                if method=='tracking_start' and code==0:self.sdk['starts']+=1
                if method=='tracking_stop' and code==0:self.sdk['stops']+=1
            def event(v):
                if v.get('event')=='tracking_decision':self.sdk_reasons[v.get('reason','unknown')]+=1
                if v.get('event')=='sdk_call' and v.get('method')=='set_speed' and any(v['args']):self.sdk['nonzero_speeds']+=1
            control.completed.connect(result);control.failed.connect(self.sdk_errors.append);control.tracking_event.connect(event)
        CameraControlService.__init__=control_init
        self.window=QWidget();self.window.setWindowTitle('Single real USB / empty / '+args.mode);self.window.resize(1450,900);self.window.setStyleSheet('background:#0d121a;color:#e0e0e0;')
        layout=QVBoxLayout(self.window);self.banner=QLabel('Unmanned, production single USB and live camera');layout.addWidget(self.banner)
        body=QHBoxLayout();layout.addLayout(body);self.view=ExecutionView();body.addWidget(self.view,4);body.addWidget(self.view._ground_track,1)
        self.cfg=WalkingConfig() if args.mode=='walk' else OvergroundRunningConfig();self.view.configure(self.cfg);self.view._camera_start_timer.stop()
        self.panel=self.view._camera_panel;self.panel.setEnabled(True);self.panel.set_camera_type('tinyse');self.panel._show_pose_action.setChecked(True);self.panel._chk_sdk_tracking.setChecked(True)
        for b in (self.view.btn_logi_camera,self.view.btn_tinyse_camera,self.view.btn_basic_camera):b.setEnabled(False)
        self.controller=SessionController()
        for signal,slot in [('device_state_changed','on_device_state'),('device_layout_changed','on_device_layout'),('walking_readiness_changed','on_walking_readiness'),('session_started','on_session_started'),('gait_snapshot','on_gait_snapshot'),('footprint_visual_frame','on_footprint_visual_frame'),('beam_quality_notice','on_beam_quality_notice')]:getattr(self.controller,signal).connect(getattr(self.view,slot))
        self.controller.walking_readiness_changed.connect(self.ready);self.controller.session_started.connect(self.armed);self.controller.session_finished.connect(self.finished)
        self.checker=QTimer(self);self.checker.setInterval(100);self.checker.timeout.connect(self.check)
        self.stopper=QTimer(self);self.stopper.setSingleShot(True);self.stopper.setTimerType(Qt.PreciseTimer);self.stopper.timeout.connect(self.stop)
        self.watchdog=QTimer(self);self.watchdog.setSingleShot(True);self.watchdog.timeout.connect(self.timeout)
        self.handling_exception=False;sys.excepthook=self.exception
        self.window.show();self.panel.start_preview();self.begin('cold')
    def exception(self,kind,value,tb):
        if self.handling_exception:return sys.__excepthook__(kind,value,tb)
        self.handling_exception=True;self.errors.append(''.join(traceback.format_exception(kind,value,tb)))
        self.checker.stop();self.stopper.stop();self.watchdog.stop()
        (self.args.output/'exception.json').write_text(json.dumps(self.errors))
        self.controller.session_finished.disconnect(self.finished)
        if self.probe:self.probe.close()
        if self.controller.is_running:self.controller.stop('experiment_error')
        else:self.controller.discard()
        self.finish_all()
    def begin(self,phase):
        self.phase=phase;self.status={};self.started=False;self.probe=None;
        if hasattr(self,'stop_request_ns'):del self.stop_request_ns
        self.banner.setText('One real USB / '+self.args.mode+' / '+phase+' / empty');self.prepare_ns=time.perf_counter_ns()
        self.controller.prepare(self.cfg);assert type(self.controller._worker) is UsbWorker
        self.refs=(self.controller._engine,self.controller._quality,self.controller._frame_inbox,self.controller._worker)
        self.checker.start();self.watchdog.start(120000)
    @Slot(dict)
    def ready(self,v):self.status=dict(v)
    @Slot()
    def check(self):
        if self.started:return
        if self.status.get('ready') and self.sdk['starts'] and self.visual['renders']>0 and self.panel._capture is not None and self.panel._capture._running:
            self.checker.stop();self.controller.start(acknowledge_quality=True,quality_key=self.status['device_key'])
    @Slot()
    def armed(self):
        self.started=True;self.arm_ns=time.perf_counter_ns();self.start_visual=dict(self.visual);self.start_sdk=dict(self.sdk);self.start_reasons=dict(self.sdk_reasons);self.start_native=native_stats(self.panel)
        self.arm_status={k:v for k,v in self.status.items() if k in ('ready','segment_count','nominal_length_m','bad_indices','transient_indices','pending_indices','requires_acknowledgement','message','details')}
        self.readers_at_start=readers();assert len(self.readers_at_start)==1
        assert self.panel._sdk_tracking and self.panel._show_pose_action.isChecked() and self.panel.isEnabled() and not self.panel._replay_mode
        self.stopper.start((5 if self.args.smoke else 30)*1000)
        if self.args.smoke:QTimer.singleShot(1500,lambda:self.window.grab().save(str(self.args.output/(self.phase+'_preview.png'))))
    @Slot()
    def stop(self):
        self.stop_request_ns=time.perf_counter_ns();self.end_visual=dict(self.visual);self.end_sdk=dict(self.sdk);self.end_reasons=dict(self.sdk_reasons);self.end_native=native_stats(self.panel)
        self.controller.stop('manual')
    @Slot(object)
    def finished(self,report):
        self.watchdog.stop();self.checker.stop();self.stopper.stop()
        if not hasattr(self,'stop_request_ns') or not self.started:self.errors.append('unexpected session finish')
        self.probe.close();engine,quality,inbox,worker=self.refs
        out=self.args.output/self.phase;out.mkdir()
        bits=np.frombuffer(b''.join(engine.overground.frames),np.uint8).reshape(len(engine.overground.frames),-1).copy();timestamps=np.array(engine.overground.timestamps)
        np.savez_compressed(out/'raw_archive.npz',bits=bits,device_timestamps=timestamps)
        full=asdict(report);full.pop('export_frames',None);full.pop('export_timestamps',None);(out/'report.json').write_text(json.dumps(full,ensure_ascii=False),encoding='utf-8')
        runtime=quality._runtime;wh=hashlib.sha256()
        for b,c in runtime._window:wh.update(b.tobytes());wh.update(c.tobytes())
        state={'quality':quality.snapshot(),'runtime_counts':runtime._counts.tolist(),'runtime_transitions':runtime._transitions.tolist(),'runtime_healthy':runtime.healthy_samples,'runtime_window_sha256':wh.hexdigest(),'audit':engine.overground.processor.event_audit,'timeline':list(engine.overground.processor.timeline),'mirror_events':engine.overground._frame_filter.mirror_guard.events,'raw_archive_sha256':hashlib.sha256(bits.tobytes()).hexdigest()}
        m={'mode':self.args.mode,'phase':self.phase,'smoke':self.args.smoke,'pid':os.getpid(),'process_start_ns':self.process_start_ns,'prepare_ns':self.prepare_ns,'armed_ns':self.arm_ns,'first_render_ns':self.first_render_ns,'stop_request_ns':self.stop_request_ns,'stop_finished_ns':time.perf_counter_ns(),'queue_final':self.probe.snapshot(inbox),'queue_common':self.probe.common,'queue_samples':self.probe.samples,'visual_start':self.start_visual,'visual_end':self.end_visual,'SDK_start':self.start_sdk,'SDK_end':self.end_sdk,'SDK_reasons_start':self.start_reasons,'SDK_reasons_end':self.end_reasons,'SDK_errors':self.sdk_errors,'native_start':self.start_native,'native_end':self.end_native,'readers_at_start':self.readers_at_start,'readers_after_stop':readers(),'threads':{'gui':self.gui_tid,'consumer':self.consumer_tid},'state':state,'status_at_arm':self.arm_status,'raw_total':engine.overground.total_frames,'raw_retained':len(bits),'wire_archive_added':False,'worker_class':type(worker).__module__+'.'+type(worker).__name__,'renderer_file':GroundChannelWidget.paintEvent.__code__.co_filename,'qt_platform':self.app.platformName(),'features':{'camera_enabled':self.panel.isEnabled(),'SDK_checked':self.panel._chk_sdk_tracking.isChecked(),'pose_checked':self.panel._show_pose_action.isChecked(),'vision_alive':self.panel._vision is not None,'recording':self.panel._capture.is_recording},'source_hashes':{p.name:sha(p) for p in (HERE/'runner.py',HERE/'queue_probe.py',HERE/'plan.json')},'errors':self.errors}
        (out/'measurement.json').write_text(json.dumps(m,ensure_ascii=False),encoding='utf-8');self.completed.append(self.phase)
        (self.args.output/'progress.json').write_text(json.dumps({'completed':self.completed,'pid':os.getpid()}))
        self.refs=None;self.probe=None;del engine,quality,inbox,worker,report,full,bits,timestamps,state,m,runtime
        if self.phase=='cold' and not self.errors:QTimer.singleShot(3000,lambda:self.begin('warm'))
        else:self.finish_all()
    def finish_all(self):
        self.panel.shutdown();self.close_loop=QEventLoop();control=self.panel._closing_control
        if control is not None:control.closed.connect(self.close_loop.quit);QTimer.singleShot(6000,self.close_loop.quit);self.close_loop.exec()
        if self.panel._closing_control is not None or self.panel._control_stop_failed:self.errors.append('SDK close not confirmed')
        (self.args.output/'pair.json').write_text(json.dumps({'completed':self.completed,'errors':self.errors,'SDK':self.sdk,'SDK_errors':self.sdk_errors,'readers_after_all':readers(),'frozen_sources_sha256':sha(HERE/'frozen_sources.json')},indent=2))
        self.app.quit()
    @Slot()
    def timeout(self):
        self.errors.append('watchdog');self.checker.stop();self.stopper.stop()
        (self.args.output/'failure.json').write_text(json.dumps({'phase':self.phase,'status':self.status,'SDK':self.sdk,'SDK_errors':self.sdk_errors,'visual':self.visual,'reader_count':len(readers())},default=str))
        if self.controller.is_running:self.stop()
        else:self.controller.discard();self.finish_all()

def main(args):
    args.output.mkdir(parents=True,exist_ok=False)
    base=json.loads((ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
    assert all(sha(ROOT/n)==v for n,v in base.items())
    frozen=json.loads((HERE/'frozen_sources.json').read_text());assert all(sha(ROOT/n)==v for n,v in frozen['files'].items())
    assert sha(HERE/'queue_probe.py')=='b3b5715ac2d4c191098499458528ff2d9f5495bd5bb6966dc1776ecb0e5105b3'
    assert GroundChannelWidget.paintEvent.__module__=='ui.ground_track'
    app=QApplication([]);run=Run(args,app);app.exec()
    assert run.completed==['cold','warm'] and not run.errors and not run.sdk_errors,(run.completed,run.errors,run.sdk_errors)
    assert run.sdk['stops']>0 and not readers()
    return 0
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--mode',choices=('walk','run'),required=True);p.add_argument('--smoke',action='store_true');raise SystemExit(main(p.parse_args()))
