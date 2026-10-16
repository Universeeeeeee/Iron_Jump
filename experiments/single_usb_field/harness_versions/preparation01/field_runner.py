"""Enabled production single-USB field acquisition. No replay or candidate renderer."""
import argparse, hashlib, json, os, sys, threading, time, traceback
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]; sys.path.insert(0,str(ROOT))
from qtpy.QtCore import QObject, QEventLoop, QTimer, Qt, Slot
from qtpy.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from ui.session_controller import SessionController, _GroundFrameInbox
from hardware.usb_worker import UsbWorker
from ui.views.execution_view import ExecutionView
from ui.embedded_camera_panel import EmbeddedCameraPanel
from ui.annotation_canvas import AnnotationCanvas
from ui.ground_track import GroundChannelWidget
from camera.control_service import CameraControlService
from queue_probe import QueueProbe

def now(): return time.perf_counter_ns()
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def structure(v): return {k:getattr(v,k) for k,_ in v._fields_}
def readers(): return [{'tid':t.native_id,'name':t.name} for t in threading.enumerate() if t.name=='CyUsbInterfaceReader']
def write(p,v): p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

class Run(QObject):
    def __init__(self,args,app):
        super().__init__(); self.args=args; self.app=app; self.errors=[]; self.sdk_errors=[]
        self.probe=None; self.raw_batches=[]; self.telemetry=[]; self.sdk_events=[]; self.visual_events=[]; self.paints={}
        self.visual={'renders':0,'pose_draw_calls':0,'valid_pose_draws':0,'valid_nodes_drawn':0,'valid_links_drawn':0}
        self.sdk={'starts':0,'stops':0,'nonzero_speeds':0}; self.reasons=Counter()
        self.status={}; self.arm_ns=None; self.stop_request_ns=None; self.record_path=None; self.record_begin=None
        self.body_since=None; self.body_count=0; self.pose_since=None; self.last_valid_draw=0; self.prepared=None
        self.marks=[]; self.serialized=False; self.gui_tid=threading.get_native_id(); self.consumer_tid=None
        original_consume=_GroundFrameInbox._consume
        def consume(inbox,items):
            if items:
                self.raw_batches.append(items)  # One retained batch reference; no extra USB callback.
                if self.probe is None:
                    first=next((v for issue,v in items if not issue),None)
                    if first is not None:
                        self.probe=QueueProbe(first.sample_index,True); self.probe.start(inbox)
                        self.consumer_tid=threading.get_native_id()
            if self.probe:return self.probe.consume(inbox,items,original_consume)
            return original_consume(inbox,items)
        _GroundFrameInbox._consume=consume
        original_render=EmbeddedCameraPanel._render_frame
        def render(panel,frame):
            self.visual['renders']+=1
            return original_render(panel,frame)
        EmbeddedCameraPanel._render_frame=render
        original_draw=AnnotationCanvas._draw_live_pose
        def draw(canvas,painter,rect):
            overlay=canvas._live_pose[0]; nodes=overlay['nodes']; stamp=now()
            n=sum(v['valid'] for v in nodes.values()); links=sum(nodes[a]['valid'] and nodes[b]['valid'] for a,b in overlay['connections'])
            self.visual['pose_draw_calls']+=1; self.visual['valid_nodes_drawn']+=n; self.visual['valid_links_drawn']+=links
            self.visual['valid_pose_draws']+=int(links>0)
            if n>=8 and links>=6:
                if stamp-self.last_valid_draw>300000000:self.pose_since=stamp
                self.last_valid_draw=stamp
            else:self.pose_since=None
            return original_draw(canvas,painter,rect)
        AnnotationCanvas._draw_live_pose=draw
        original_paint=GroundChannelWidget.paintEvent
        def paint(widget,event):
            original_paint(widget,event)
            if hasattr(self,'view') and widget is self.view._ground_track.channel:
                stamp=now()
                for foot in widget._feet+widget.history:
                    cid=foot.get('contact_id')
                    if cid is not None and foot.get('status')=='confirmed' and cid not in self.paints:self.paints[cid]=stamp
        GroundChannelWidget.paintEvent=paint
        original_control=CameraControlService.__init__
        def control_init(control,*a,**kw):
            original_control(control,*a,**kw)
            def result(method,code):
                self.sdk_events.append({'host_ns':now(),'completed':method,'result':code})
                if code<0:self.sdk_errors.append([method,code])
                if method=='tracking_start' and code==0:self.sdk['starts']+=1
                if method=='tracking_stop' and code==0:self.sdk['stops']+=1
            def event(v):
                self.sdk_events.append({'host_ns':now(),'event':v})
                if v.get('event')=='tracking_decision':self.reasons[v.get('reason','unknown')]+=1
                if v.get('event')=='sdk_call' and v.get('method')=='set_speed' and any(v['args']):self.sdk['nonzero_speeds']+=1
            control.completed.connect(result); control.failed.connect(self.sdk_errors.append); control.tracking_event.connect(event)
        CameraControlService.__init__=control_init
        self.window=QWidget(); self.window.setWindowTitle('现场单 USB · '+args.mode); self.window.resize(1450,900)
        self.window.setStyleSheet('background:#0d121a;color:#e0e0e0; font-size:17px;')
        layout=QVBoxLayout(self.window); self.banner=QLabel('准备：全身入镜，站在光栅外；请等待录像、SDK、骨架核验。'); layout.addWidget(self.banner)
        self.confirm=QCheckBox('现场已确认头到脚完整入镜、跑道清空；只去程通过一次，从跑道外离开'); layout.addWidget(self.confirm)
        self.start_button=QPushButton('确认条件后开始（5 秒空场倒计时）'); layout.addWidget(self.start_button)
        self.start_button.clicked.connect(self.start); self.start_button.setEnabled(False)
        self.clear_button=QPushButton('人已离开光栅：标记并继续 15 秒空场'); layout.addWidget(self.clear_button)
        self.clear_button.setEnabled(False); self.clear_button.clicked.connect(self.clear_mark)
        body=QHBoxLayout(); layout.addLayout(body); self.view=ExecutionView(); body.addWidget(self.view,4); body.addWidget(self.view._ground_track,1)
        self.cfg=(WalkingConfig if args.mode=='walk' else OvergroundRunningConfig)(stop_type='Software command')
        self.view.configure(self.cfg); self.view._camera_start_timer.stop(); self.view.set_quality_preflight_required(True)
        self.panel=self.view._camera_panel; self.panel.setEnabled(True); self.panel.set_camera_type('tinyse')
        self.panel._show_pose_action.setChecked(True); self.panel._chk_sdk_tracking.setChecked(True)
        self.view.btn_start.hide()
        for b in (self.view.btn_logi_camera,self.view.btn_tinyse_camera,self.view.btn_basic_camera):b.setEnabled(False)
        self.controller=SessionController()
        for signal,slot in [('device_state_changed','on_device_state'),('device_layout_changed','on_device_layout'),('walking_readiness_changed','on_walking_readiness'),('session_started','on_session_started'),('gait_snapshot','on_gait_snapshot'),('footprint_visual_frame','on_footprint_visual_frame'),('beam_quality_notice','on_beam_quality_notice')]:getattr(self.controller,signal).connect(getattr(self.view,slot))
        self.controller.walking_readiness_changed.connect(self.ready); self.controller.session_started.connect(self.armed)
        self.controller.session_finished.connect(self.finished); self.controller.footprint_visual_frame.connect(self.visual_event)
        self.view.stop_requested.connect(self.stop)
        self.timer=QTimer(self); self.timer.setInterval(1000); self.timer.timeout.connect(self.progress)
        self.stopper=QTimer(self); self.stopper.setSingleShot(True); self.stopper.setTimerType(Qt.PreciseTimer); self.stopper.timeout.connect(self.stop)
        self.watchdog=QTimer(self); self.watchdog.setSingleShot(True); self.watchdog.timeout.connect(self.timeout)
        self.handling_exception=False; sys.excepthook=self.exception
        self.window.show(); self.panel.start_preview(); self.prepare_ns=now(); self.controller.prepare(self.cfg)
        assert type(self.controller._worker) is UsbWorker
        self.refs=(self.controller._engine,self.controller._quality,self.controller._frame_inbox)
        self.timer.start(); self.watchdog.start(900000)
    @Slot(dict)
    def ready(self,status):self.status=dict(status)
    @Slot(dict)
    def visual_event(self,v):self.visual_events.append({'host_ns':now(),'frame':v})
    def mark(self,name):self.marks.append({'host_ns':now(),'name':name})
    @Slot()
    def progress(self):
        stamp=now(); capture=self.panel._capture
        if self.arm_ns is None:
            if capture is not None and capture._running and self.record_path is None and self.sdk['starts']:
                self.record_begin=now(); self.record_path=capture.start_record(self.args.output/'camera',preserve_raw=True); self.record_return=now()
                if self.record_path is None:raise RuntimeError('原始录像启动失败')
                write(self.args.output/'camera_record_start.json',{'before_ns':self.record_begin,'after_ns':self.record_return,'path':self.record_path,'preserve_raw':True})
            pose,state,_=self.panel._vision.display_state() if self.panel._vision is not None else (None,'disabled',None)
            landmarks=getattr(pose,'landmarks_33',None)
            full=bool(landmarks and all(landmarks[k].quality>=.65 and 0<=landmarks[k].x<=1 and 0<=landmarks[k].y<=1 for k in (0,11,12,23,24,25,26,27,28)))
            if full:
                if self.body_since is None:self.body_since=stamp
            else:self.body_since=None
            drawn=self.pose_since is not None and stamp-self.pose_since>=2000000000 and stamp-self.last_valid_draw<=1000000000
            record=structure(capture._capture.record_stats()) if self.record_path else None
            ready=bool(self.status.get('ready') and self.sdk['starts'] and full and self.body_since is not None and stamp-self.body_since>=2000000000 and drawn and record and record['frames_written']>0 and Path(self.record_path).stat().st_size>0)
            if ready and self.prepared is None:
                self.prepared={'host_ns':stamp,'full_body_valid_since':self.body_since,'actual_lower_body_draw_since':self.pose_since,'visual':dict(self.visual),'record_stats':record}
                self.window.grab().save(str(self.args.output/'preparation.png'))
            self.start_button.setEnabled(ready and self.confirm.isChecked())
            self.banner.setText(f"准备 {self.args.mode}：USB就绪={self.status.get('ready',False)} 全身连续有效={full} 骨架持续绘制={drawn} 录像帧={record['frames_written'] if record else 0}；确认勾选后点击上方开始")
            write(self.args.output/'ready.json',{'host_ns':stamp,'ready':ready,'checked':self.confirm.isChecked(),'visual':self.visual,'SDK':self.sdk,'full_body':full,'body_since':self.body_since,'pose_since':self.pose_since})
        else:
            elapsed=(stamp-self.arm_ns)/1e9
            if elapsed<5:self.banner.setText(f'{self.args.mode} 已录像：保持光栅空场，还需 {5-elapsed:.1f} 秒')
            elif not any(v['name']=='operator_clear' for v in self.marks):self.banner.setText(f'{self.args.mode} {elapsed:.0f} 秒：现在单次通过，从跑道外离开；助手随后点击“人已离开”')
            self.telemetry.append({'host_ns':stamp,'visual':dict(self.visual),'SDK':dict(self.sdk),'last_valid_draw_ns':self.last_valid_draw})
    @Slot()
    def start(self):
        if self.arm_ns is not None:return
        if not self.start_button.isEnabled():return
        self.start_button.setEnabled(False); self.confirm.setEnabled(False)
        self.controller.start(acknowledge_quality=True,quality_key=self.status['device_key'])
    @Slot()
    def armed(self):
        self.arm_ns=now(); self.start_visual=dict(self.visual); self.start_native=structure(self.panel._capture._capture.stats())
        self.start_sdk=dict(self.sdk); self.start_button.hide(); self.view.btn_start.hide(); self.clear_button.setEnabled(True)
        self.readers_at_start=readers(); assert len(self.readers_at_start)==1 and self.panel._capture.is_recording
        self.mark('armed_empty_start'); self.stopper.start(60000); self.watchdog.start(120000)
        QTimer.singleShot(5000,self.go)
        write(self.args.output/'armed.json',{'host_ns':self.arm_ns,'mode':self.args.mode,'pid':os.getpid()})
    def go(self):
        if self.stop_request_ns is None:self.mark('go_after_5s'); QApplication.beep()
    @Slot()
    def clear_mark(self):
        if self.arm_ns is None or now()-self.arm_ns<5000000000:return
        self.mark('operator_clear'); self.clear_button.setEnabled(False); self.banner.setText('人已离开：继续空场 15 秒，请勿返回光栅内'); self.stopper.start(15000)
    @Slot()
    def stop(self):
        if not self.controller.is_running:return
        self.stop_request_ns=now(); self.mark('stop_requested'); self.timer.stop(); self.stopper.stop(); self.watchdog.stop()
        self.end_visual=dict(self.visual); self.end_sdk=dict(self.sdk); self.end_native=structure(self.panel._capture._capture.stats())
        self.banner.setText('采集结束，正在保存原始录像、数据和报告……'); self.controller.stop('manual')
    @Slot(object)
    def finished(self,report):
        self.stop_callback_ns=now(); self.timer.stop(); self.watchdog.stop(); self.stopper.stop()
        if self.stop_request_ns is None:
            self.errors.append('unexpected_auto_finish'); self.stop_request_ns=now(); self.end_visual=dict(self.visual); self.end_sdk=dict(self.sdk); self.end_native=structure(self.panel._capture._capture.stats())
        self.probe.close(); engine,quality,inbox=self.refs; final=self.probe.snapshot(inbox)
        self.panel._capture.stop_record(wait=True); self.record_end=now(); record_stats=structure(self.panel._capture.last_record_stats)
        write(self.args.output/'camera_record_end.json',{'host_ns':self.record_end,'path':self.record_path,'stats':record_stats})
        bits=np.frombuffer(b''.join(engine.overground.frames),np.uint8).reshape(len(engine.overground.frames),-1).copy()
        np.savez_compressed(self.args.output/'raw_archive.npz',bits=bits,device_timestamps=np.array(engine.overground.timestamps))
        raw=[v for items in self.raw_batches for issue,v in items if not issue]; issues=[asdict(v) for items in self.raw_batches for issue,v in items if issue]
        np.savez_compressed(self.args.output/'raw_frames.npz',bits=np.array([np.frombuffer(v.contact_bits,np.uint8) for v in raw]),wire=np.array([np.frombuffer(v.wire_payload,np.uint8) for v in raw]),valid_bits=np.array([np.frombuffer(v.valid_bits,np.uint8) for v in raw]),sample_indices=np.array([v.sample_index for v in raw]),frame_indices=np.array([v.frame_index for v in raw]),received_ns=np.array([v.received_monotonic_ns for v in raw]),dropped_frames_before=np.array([v.dropped_frames_before for v in raw]))
        write(self.args.output/'acquisition.json',{'issues':issues,'events':[('issue' if issue else 'frame',v.code if issue else v.sample_index) for items in self.raw_batches for issue,v in items],'frames':[{'stream_id':v.stream_id,'quality_flags':v.quality_flags} for v in raw],'layouts':{v.stream_id:asdict(v.layout) for v in raw}})
        full=asdict(report); full.pop('export_frames',None); full.pop('export_timestamps',None); write(self.args.output/'report.json',full)
        runtime=quality._runtime; wh=hashlib.sha256()
        for b,c in runtime._window:wh.update(b.tobytes()); wh.update(c.tobytes())
        write(self.args.output/'state.json',{'quality':quality.snapshot(),'runtime_counts':runtime._counts.tolist(),'runtime_transitions':runtime._transitions.tolist(),'runtime_healthy':runtime.healthy_samples,'runtime_window_sha256':wh.hexdigest(),'audit':engine.overground.processor.event_audit,'timeline':list(engine.overground.processor.timeline),'mirror_events':engine.overground._frame_filter.mirror_guard.events})
        write(self.args.output/'visual_events.json',self.visual_events); write(self.args.output/'SDK_events.json',self.sdk_events)
        self.measurement={'mode':self.args.mode,'pid':os.getpid(),'armed_ns':self.arm_ns,'stop_request_ns':self.stop_request_ns,'stop_callback_ns':self.stop_callback_ns,'queue_common':self.probe.common,'queue_samples':self.probe.samples,'queue_final':final,'visual_start':self.start_visual,'visual_end':self.end_visual,'SDK_start':self.start_sdk,'SDK_end':self.end_sdk,'native_start':self.start_native,'native_end':self.end_native,'telemetry':self.telemetry,'marks':self.marks,'prepared':self.prepared,'paints':self.paints,'raw_total':engine.overground.total_frames,'raw_retained':len(bits),'raw_archive_sha256':hashlib.sha256(bits.tobytes()).hexdigest(),'readers_at_start':self.readers_at_start,'readers_after_stop':readers(),'threads':{'gui':self.gui_tid,'consumer':self.consumer_tid},'record_stats':record_stats,'renderer_file':original_renderer,'errors':self.errors,'SDK_errors':self.sdk_errors,'frozen_sources_sha256':sha(HERE/'frozen_sources.json')}
        self.serialized=True; self.close()
    def close(self):
        self.panel.shutdown(); control=self.panel._closing_control
        if control is not None:
            loop=QEventLoop(); control.closed.connect(loop.quit); QTimer.singleShot(6000,loop.quit); loop.exec()
        if self.panel._closing_control is not None or self.panel._control_stop_failed:self.errors.append('SDK close unconfirmed')
        write(self.args.output/'shutdown.json',{'serialized':self.serialized,'SDK':self.sdk,'SDK_errors':self.sdk_errors,'errors':self.errors,'readers':readers()})
        if self.serialized:
            self.measurement['errors']=self.errors; self.measurement['SDK_errors']=self.sdk_errors; write(self.args.output/'measurement.json',self.measurement)
            write(self.args.output/'SDK_events.json',self.sdk_events)
        self.app.quit()
    def timeout(self):
        self.errors.append('watchdog_timeout')
        if self.controller.is_running:self.stop()
        else:self.timer.stop(); self.controller.discard(); self.close()
    def exception(self,kind,value,tb):
        if self.handling_exception:return sys.__excepthook__(kind,value,tb)
        self.handling_exception=True; self.errors.append(''.join(traceback.format_exception(kind,value,tb)))
        write(self.args.output/'exception.json',self.errors); self.timer.stop(); self.watchdog.stop(); self.stopper.stop()
        if self.probe:self.probe.close()
        self.controller.session_finished.disconnect(self.finished)
        if self.controller.is_running:self.controller.stop('experiment_error')
        else:self.controller.discard()
        if self.record_path and self.panel._capture:self.panel._capture.stop_record(wait=True)
        self.close()

def main(args):
    args.output.mkdir(parents=True,exist_ok=False)
    base=json.loads((ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
    assert all(sha(ROOT/n)==v for n,v in base.items())
    assert all(sha(ROOT/n)==v for n,v in json.loads((HERE/'frozen_sources.json').read_text())['files'].items())
    assert sha(HERE/'queue_probe.py')=='b3b5715ac2d4c191098499458528ff2d9f5495bd5bb6966dc1776ecb0e5105b3'
    assert GroundChannelWidget.paintEvent.__module__=='ui.ground_track'
    global original_renderer
    original_renderer=GroundChannelWidget.paintEvent.__code__.co_filename
    app=QApplication([]); run=Run(args,app); app.exec()
    assert run.serialized and not run.errors and not run.sdk_errors
    assert run.sdk['stops']>0 and not readers()
    return 0
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True); p.add_argument('--mode',choices=('walk','run'),required=True)
    raise SystemExit(main(p.parse_args()))
