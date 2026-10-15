"""Same production reader inbox, session, ExecutionView and paint boundary; no subject storage."""
import argparse
import csv
import hashlib
import importlib.util
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
from qtpy.QtCore import QObject, QEventLoop, Qt, QTimer, Signal, Slot
from qtpy.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.modes.walking_processor import WalkingProcessor
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from hardware.sensor_frame import DeviceLayout, SensorSegment, SensorFrame
from hardware.usb_worker import UsbWorker
from ui.session_controller import SessionController
from ui.ground_track import GroundChannelWidget
from ui.views.execution_view import ExecutionView


class OfflineWorker(QObject):
    data_received = Signal(str)
    device_state_changed = Signal(str, str)
    sensor_frame_received = Signal(object)
    acquisition_issue = Signal(object)
    layout_detected = Signal(object)
    exhausted = Signal()

    def __init__(self, profile, folder, cadence, **kwargs):
        super().__init__()
        self.folder=folder;self.cadence=cadence
        self.cancel=threading.Event();self.reader=None;self.anchor_ns=None
        self.arm_ready=threading.Event();self.arm_pause_ns=0
        self.meta=json.loads((folder/'report.json').read_text(encoding='utf-8'))['report_config_snapshot']
        d=self.meta['device'];g=d['layout']
        self.layout=DeviceLayout(tuple(SensorSegment(**v) for v in g['segments']),tuple(g['invalid_bit_indices']))
        self.stream_id=d['stream_id']
        touches=json.loads((folder/'timing.json').read_text(encoding='utf-8'))['rows']
        last=max(v['touch_sample'] for v in touches)+1200
        with np.load(folder/'raw_frames.npz') as raw:
            mask=(raw['sample_indices']>=d['checked_sample_index']-3500)&(raw['sample_indices']<=last)
            self.data={k:raw[k][mask] for k in raw.files}
        self.indices=self.data['sample_indices']
        times=self.data['received_ns'] if cadence=='recorded' else self.indices*1000000
        self.offsets=times-times[0]
        self.lookup={int(n):int(t) for n,t in zip(self.indices,self.offsets)}
        self.original_start_ns=int(self.data['received_ns'][0])

    @Slot()
    def connect_device(self):self.device_state_changed.emit('connected','Recorded raw source')

    @Slot()
    def prepare_walking_capture(self):self.start_capture()

    @Slot()
    def start_capture(self):
        if self.reader:return
        self.layout_detected.emit(self.layout)
        self.device_state_changed.emit('streaming','Recorded raw source')
        def read():
            self.cancel.wait(3.0)
            self.anchor_ns=time.perf_counter_ns()
            for k,n in enumerate(self.indices):
                if self.cancel.wait(max(0,(self.anchor_ns+int(self.offsets[k])-time.perf_counter_ns())/1e9)):return
                frame=SensorFrame(self.stream_id,self.layout,int(self.data['frame_indices'][k]),int(n),time.perf_counter_ns(),
                    self.data['bits'][k].tobytes(),b'\x01'*self.layout.bit_count,self.data['wire'][k].tobytes())
                self.sensor_frame_received.emit(frame)
                if n==self.meta['device']['checked_sample_index']:
                    pause=time.perf_counter_ns()
                    if not self.arm_ready.wait(2):raise RuntimeError('Fixed-sample arm timed out')
                    self.arm_pause_ns=time.perf_counter_ns()-pause
                    self.anchor_ns+=self.arm_pause_ns
            self.exhausted_ns=time.perf_counter_ns()
            self.exhausted.emit()
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()

    @Slot()
    def stop(self):
        self.cancel.set()
        if self.reader:self.reader.join(2)


def replay_camera(panel, worker, stop, stats):
    # Read only recorded JPEGs; never opens USB, camera drivers or SDK controls.
    import cv2
    from camera.tinyse_camera import TinySeFrameTiming
    with (worker.folder/'camera.csv').open() as stream:rows=list(csv.DictReader(stream))
    record_ns=json.loads((worker.folder/'camera_record_start.json').read_text(encoding='utf-8'))['host_ns']
    relative=(record_ns-worker.original_start_ns)/1e9
    last=-1
    with (worker.folder/'camera.mjpg').open('rb') as source:
        for row in rows:
            elapsed=float(row['record_elapsed_seconds'])
            if elapsed-last<1/30:continue
            last=elapsed
            due_ns=worker.anchor_ns+round((relative+elapsed)*1e9)
            if time.perf_counter_ns()>due_ns+33333333:
                stats['stale_frames_skipped']=stats.get('stale_frames_skipped',0)+1;continue
            if stop.wait(max(0,(due_ns-time.perf_counter_ns())/1e9)):return
            source.seek(int(row['offset']));data=source.read(int(row['length']))
            frame=cv2.imdecode(np.frombuffer(data,dtype=np.uint8),cv2.IMREAD_COLOR)
            if frame is None:raise RuntimeError('Recorded JPEG decode failed')
            now=time.perf_counter()
            timing=TinySeFrameTiming(int(row['capture_frame_index']),float(row['sample_time']),now,now)
            panel._submit_vision_frame(frame,timing)
            if panel._chk_mirror.isChecked():frame=cv2.flip(frame,1)
            panel._queue_preview_frame(frame)
            stats['decoded_frames']+=1


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'protocol.json').write_text(json.dumps({'source':args.source,'mode':args.mode,'starting_foot':args.starting_foot,'duration_s':args.seconds,'p95_limit_ms':150,'max_limit_ms':250,'physical_ground_truth':'pending现场动作/录像核对'},ensure_ascii=False),encoding='utf-8')
    meta=json.loads((args.input/'report.json').read_text(encoding='utf-8'))['report_config_snapshot']
    cache=None
    if args.paint=='gui_final_v2':
        spec=importlib.util.spec_from_file_location('gui_final_v2_cache',args.cache_file)
        cache=importlib.util.module_from_spec(spec);spec.loader.exec_module(cache);cache.install()
    from ui.footprint_channel import FootprintChannelWidget
    provenance={'input_sha256':hashlib.sha256((args.input/'raw_frames.npz').read_bytes()).hexdigest(),
        'paint':args.paint,'paint_function_file':FootprintChannelWidget.paintEvent.__code__.co_filename,
        'cache_sha256':hashlib.sha256(args.cache_file.read_bytes()).hexdigest() if cache else None,
        'cadence':args.cadence,'camera_replay':args.camera_replay,'arm_protocol':'pause reader at original checked sample; resume and rebase host schedule after arm',
        'source_hashes':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in
            ('ui/footprint_channel.py','ui/ground_track.py','engine/overground_session.py','engine/modes/overground_running_processor.py','hardware/beam_filter.py','hardware/payload_mirror.py')}}
    (args.output/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    app = QApplication([])
    receipts, raw, rows, paints, visuals = {}, [], {}, {}, []
    filtered_delays, queue_sizes = [], []
    confirmed = {}
    factory = WalkingProcessor if args.mode == 'walk' else OvergroundRunningProcessor
    process = factory.process
    def measured_process(p, frame, **kwargs):
        process(p, frame, **kwargs)
        wall = time.perf_counter_ns()
        for c in p.contacts:
            if c.confirmed and c.id not in confirmed:
                device_confirm = (round(c.confirmed_at*1000) if args.mode == 'walk'
                                  else c.confirmed_sample)
                confirmed[c.id] = (device_confirm, wall)
        for event in p.touch_events:
            cid = event['contact_id']
            if event['active'] and cid not in rows:
                device_confirm, confirm_wall = confirmed.get(cid, (None, None))
                rows[cid] = {**event, 'confirmed_sample':device_confirm,
                             'confirmed_host_ns':confirm_wall, 'published_host_ns':wall,
                             'touch_received_host_ns':receipts.get(event['touch_sample'])}
    factory.process = measured_process
    controller = SessionController(worker_factory=(lambda **kw:OfflineWorker(args.profile,args.input,args.cadence,**kw))
                                   if args.source == 'offline' else None)
    window = QWidget(); window.setWindowTitle('IronJump v1.15 isolated validation / '+args.mode)
    window.resize(1450,900); window.setStyleSheet('background:#0d121a;color:#e0e0e0;')
    outer=QVBoxLayout(window); banner=QLabel('Keep the lane clear until ready.');outer.addWidget(banner)
    body=QHBoxLayout();outer.addLayout(body)
    view=ExecutionView();body.addWidget(view,4);body.addWidget(view._ground_track,1)
    config_class=WalkingConfig if args.mode=='walk' else OvergroundRunningConfig
    cfg=config_class(**{k:v for k,v in meta.items() if k in config_class.__dataclass_fields__ and config_class.__dataclass_fields__[k].init})
    view.configure(cfg);view._camera_start_timer.stop();view._camera_panel.set_vision_enabled(args.source=='usb')
    view._camera_panel.setEnabled(True)
    for b in (view.btn_logi_camera,view.btn_tinyse_camera,view.btn_basic_camera):b.setEnabled(args.source=='usb')
    view.set_quality_preflight_required(True)
    paint=GroundChannelWidget.paintEvent
    paint_times=[]
    def measured_paint(widget,event):
        begin=time.perf_counter_ns()
        paint(widget,event)
        paint_times.append({"overview":widget.overview,"wall_ms":(time.perf_counter_ns()-begin)/1e6})
        if widget is view._ground_track.channel:
            now=time.perf_counter_ns()
            for foot in widget._feet+widget.history:
                cid=foot.get('contact_id')
                if foot.get('status')=='confirmed' and cid is not None and cid not in paints:
                    paints[cid]=now
    GroundChannelWidget.paintEvent=measured_paint
    controller.device_state_changed.connect(view.on_device_state)
    controller.device_layout_changed.connect(view.on_device_layout)
    controller.walking_readiness_changed.connect(view.on_walking_readiness)
    controller.session_started.connect(view.on_session_started)
    controller.gait_snapshot.connect(view.on_gait_snapshot)
    controller.footprint_visual_frame.connect(view.on_footprint_visual_frame)
    controller.beam_quality_notice.connect(view.on_beam_quality_notice)
    started=[None];finished=[False];errors=[];status_cache={}
    def ready(status):
        status_cache.clear();status_cache.update(status)
        if args.source=='usb':
            if status.get('ready'):banner.setText('设备就绪。点击开始；5秒后单次通过跑道，从跑道外返回。请用手机拍摄双脚和屏幕。')
            return
        if (status.get('ready') and not controller.is_running and started[0] is None
                and getattr(controller._frame_inbox,'probe_last_sample',-1)==worker.meta['device']['checked_sample_index']):
            controller.start(acknowledge_quality=True,quality_key=status['device_key'])
    def armed():
        started[0]=time.perf_counter_ns()
        if args.source=='offline':worker.arm_ready.set()
        if args.source=='usb' and view._camera_panel._capture is not None:
            if not view._camera_panel._is_record_busy(view._camera_panel._capture):
                if view._camera_panel._camera_type=='tinyse':
                    view._camera_panel._record_path=view._camera_panel._capture.start_record(args.output/'camera',preserve_raw=True)
                    view._camera_panel._refresh_menu()
                else:view._camera_panel._on_record()
            (args.output/'camera_record_start.json').write_text(json.dumps({'host_ns':time.perf_counter_ns(),'path':view._camera_panel._record_path}),encoding='utf-8')
        banner.setText('采集开始：等待5秒，右脚先进入，然后单次通过8米跑道；从跑道外返回。')
        (args.output/'armed.json').write_text(json.dumps({'host_ns':started[0],'mode':args.mode}))
        if args.source=='usb':QTimer.singleShot(args.seconds*1000,delivery.on_stop)
    def record_visual(frame):
        visuals.append({'host_ns':time.perf_counter_ns(),'sample_index':frame.get('sample_index'),
                        'feet':frame.get('feet',[])})
    def shutdown_camera():
        panel=view._camera_panel
        panel.shutdown()
        control=panel._closing_control
        if control is not None:
            loop=QEventLoop();control.closed.connect(loop.quit)
            QTimer.singleShot(6000,loop.quit);loop.exec()
            if panel._closing_control is not None or panel._control_stop_failed:
                errors.append('camera_control_stop_unconfirmed')
    def report(report):
        finished[0]=True
        export_started=time.perf_counter_ns()
        payload=asdict(report)
        payload.pop('export_frames',None);payload.pop('export_timestamps',None)
        (args.output/'report.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        (args.output/'report_export.json').write_text(json.dumps({'elapsed_ms':(time.perf_counter_ns()-export_started)/1e6}))
        if args.source=='usb':
            banner.setText('光学报告已保存，正在关闭相机并保存原始录像…')
            view._camera_panel.stop_preview()
            save_timer=QTimer(window);save_timer.setInterval(100)
            def finish_camera():
                capture=view._camera_panel._capture
                if capture is not None and view._camera_panel._is_record_busy(capture):return
                save_timer.stop();shutdown_camera()
                (args.output/'camera_record_end.json').write_text(json.dumps({'host_ns':time.perf_counter_ns(),'path':str(args.output/'camera.mjpg') if view._camera_panel._camera_type=='tinyse' else view._camera_panel._last_recording_path,'raw_video_preserved':view._camera_panel._camera_type=='tinyse'}),encoding='utf-8')
                app.quit()
            save_timer.timeout.connect(finish_camera);save_timer.start()
        else:QTimer.singleShot(100,app.quit)
    class Delivery(QObject):
        @Slot(dict)
        def on_ready(self,status):ready(status)
        @Slot()
        def on_start(self):
            controller.start(acknowledge_quality=bool(status_cache.get('requires_acknowledgement')),
                             quality_key=status_cache.get('device_key'))
        @Slot()
        def on_stop(self):
            if not controller.is_running:return
            request_ns=time.perf_counter_ns()
            banner.setText('正在结束采集并保存报告…')
            view.btn_stop.setEnabled(False)
            (args.output/'stop_requested.json').write_text(json.dumps({'host_ns':request_ns}),encoding='utf-8')
            controller.stop('manual')
            (args.output/'stop_returned.json').write_text(json.dumps({'host_ns':time.perf_counter_ns(),'elapsed_ms':(time.perf_counter_ns()-request_ns)/1e6}),encoding='utf-8')
        @Slot()
        def on_armed(self):armed()
        @Slot(dict)
        def on_visual(self,frame):record_visual(frame)
        @Slot(object)
        def on_report(self,value):report(value)
        @Slot()
        def on_exhausted(self):
            def settled():
                inbox=controller._frame_inbox
                if inbox is None:return
                if getattr(inbox,'probe_last_sample',-1)<int(worker.indices[-1]):
                    QTimer.singleShot(20,settled);return
                QTimer.singleShot(200,lambda:controller.stop('manual'))
            settled()
    delivery=Delivery()
    controller.walking_readiness_changed.connect(delivery.on_ready)
    view.start_requested.connect(delivery.on_start)
    controller.session_started.connect(delivery.on_armed)
    controller.footprint_visual_frame.connect(delivery.on_visual)
    controller.session_finished.connect(delivery.on_report)
    view.stop_requested.connect(delivery.on_stop)
    controller.prepare(cfg)
    worker=controller._worker
    arm_timer=QTimer(window);arm_timer.setInterval(5)
    arm_timer.timeout.connect(lambda:ready(dict(status_cache)) if not controller.is_running and started[0] is None else None)
    arm_timer.start()
    def receive(f):
        receipts[f.sample_index]=f.received_monotonic_ns
        raw.append(f)
    worker.sensor_frame_received.connect(receive,Qt.DirectConnection)
    session=controller._engine.overground
    consume=session._consume_frames
    def measured_consume(frames):
        wall=time.perf_counter_ns()
        for f in frames:
            filtered_delays.append((wall-f.received_monotonic_ns)/1e6)
        filt=session._frame_filter
        if filt:queue_sizes.append(len(filt._queue)+int(filt.mirror_guard._pending is not None))
        consume(frames)
    session._consume_frames=measured_consume
    emit=session.publish_snapshot
    def measured_emit():
        emit()
        wall=time.perf_counter_ns()
        for cid in rows:
            if 'snapshot_emit_host_ns' not in rows[cid] and session.processor:
                rows[cid]['snapshot_emit_host_ns']=wall
    session.publish_snapshot=measured_emit
    emit_visual=session.publish_visual
    def measured_visual_emit():
        emit_visual()
        wall=time.perf_counter_ns()
        for cid in rows:
            if 'visual_emit_host_ns' not in rows[cid]:rows[cid]['visual_emit_host_ns']=wall
    session.publish_visual=measured_visual_emit
    if args.source=='offline':
        worker.exhausted.connect(delivery.on_exhausted,Qt.QueuedConnection)
    def timeout():
        if not finished[0]:
            errors.append('watchdog_timeout')
            if controller.is_running:controller.stop('manual')
            else:controller.discard();app.quit()
    QTimer.singleShot(45000,timeout)
    countdown=QTimer(window);countdown.setInterval(200)
    seen_pose=[False]
    def progress():
        if args.source=='usb':
            panel=view._camera_panel
            pose,status,check=panel._vision.display_state() if panel._vision is not None else (None,'disabled',None)
            (args.output/'camera_live.json').write_text(json.dumps({'host_ns':time.perf_counter_ns(),'preview':panel._preview_active,'preview_frame':panel._display_frame is not None,'pose_status':status,'pose_present':pose is not None,'overlay_visible':panel._overlay_visible,'sdk_tracking':panel._sdk_tracking,'tracking_notice':panel._tracking_notice},ensure_ascii=False),encoding='utf-8')
            if panel._overlay_visible and not seen_pose[0]:
                seen_pose[0]=True;window.grab().save(str(args.output/'camera_pose_ready.png'))
        if args.source=='usb' and started[0] and not finished[0]:
            elapsed=(time.perf_counter_ns()-started[0])/1e9
            instruction='保持空场，等待5秒' if elapsed<5 else ('正常走路，右脚先进入' if args.mode=='walk' else '正常跑步，右脚先进入')
            banner.setText(f'{args.mode} {elapsed:.1f}/{args.seconds} 秒 · {instruction}；单次通过，从跑道外返回')
    countdown.timeout.connect(progress);countdown.start()
    if args.source=='usb':
        view._camera_panel._chk_sdk_tracking.setChecked(True)
        QTimer.singleShot(0,view._camera_panel.start_preview)
    camera_stop=threading.Event();camera_thread=None;camera_stats={'decoded_frames':0}
    video_prepared=[False]
    def start_video():
        nonlocal camera_thread
        if not args.camera_replay:return
        panel=view._camera_panel
        if not video_prepared[0]:
            video_prepared[0]=True
            panel.set_vision_enabled(True);panel._preview_active=True
            panel._start_vision();panel._preview_timer.start()
        if worker.anchor_ns is None:
            QTimer.singleShot(10,start_video);return
        camera_thread=threading.Thread(target=replay_camera,args=(panel,worker,camera_stop,camera_stats),daemon=True)
        camera_thread.start()
    QTimer.singleShot(0,start_video)
    window.show();app.exec()
    camera_stop.set()
    if camera_thread:camera_thread.join(2)
    if controller._thread:controller.discard()
    shutdown_camera()
    window.grab().save(str(args.output/'ui.png'))
    if raw:
        np.savez_compressed(args.output/'raw_frames.npz',bits=np.array([np.frombuffer(f.contact_bits,dtype=np.uint8) for f in raw]),
            wire=np.array([np.frombuffer(f.wire_payload,dtype=np.uint8) for f in raw]),
            sample_indices=np.array([f.sample_index for f in raw]),frame_indices=np.array([f.frame_index for f in raw]),
            received_ns=np.array([f.received_monotonic_ns for f in raw]))
    for cid,row in rows.items():
        row['ui_paint_completed_host_ns']=paints.get(cid)
        row['device_confirmation_delay_ms']=(row['confirmed_sample']-row['touch_sample']) if row['confirmed_sample'] is not None else None
        if row['touch_received_host_ns'] and cid in paints:
            row['received_to_paint_ms']=(paints[cid]-row['touch_received_host_ns'])/1e6
        if args.source=='offline' and worker.anchor_ns and cid in paints:
            row['scheduled_event_to_paint_ms']=(paints[cid]-worker.anchor_ns-worker.lookup[row['touch_sample']])/1e6
    values=[r['received_to_paint_ms'] for r in rows.values() if 'received_to_paint_ms' in r]
    (args.output/'paint_times.json').write_text(json.dumps(paint_times))
    result={'camera_replay_stats':camera_stats,'source':args.source,'mode':args.mode,'profile':args.profile,'finished':finished[0],'errors':errors,
        'rows':list(rows.values()),'visual_frames':visuals,'filter_received_to_delivery_ms':{'p95':float(np.percentile(filtered_delays,95)) if filtered_delays else None,'max':max(filtered_delays,default=None)},
        'max_filter_held_frames':max(queue_sizes,default=0),'received_to_paint_ms':{'count':len(values),'p95':float(np.percentile(values,95)) if values else None,'max':max(values,default=None)},
        'source_exhausted_host_ns':getattr(worker,'exhausted_ns',None),'scope':'Qt paint completion, not physical display scanout; hardware device and host clocks are not synchronized. Receipt-to-paint excludes unknown USB transit.',
        'provisional_receipt_to_paint_pass':bool(values and np.percentile(values,95)<=150 and max(values)<=250)}
    (args.output/'timing.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','visual_frames')},ensure_ascii=False),flush=True)
    factory.process=process;GroundChannelWidget.paintEvent=paint
    return int(not finished[0] or bool(errors))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--paint',choices=('tested','gui_final_v2'),required=True);p.add_argument('--cache-file',type=Path,required=True);p.add_argument('--camera-replay',action='store_true');p.add_argument('--cadence',choices=('recorded','device'),default='recorded');p.add_argument('--source',choices=('offline','usb'),default='offline')
    p.add_argument('--mode',choices=('walk','run'),default='walk');p.add_argument('--profile',choices=('normal','mirror_fragment'),default='normal')
    p.add_argument('--starting-foot',choices=('Not defined','Left','Right'),default='Not defined');p.add_argument('--seconds',type=int,default=30);p.add_argument('--output',type=Path,required=True)
    raise SystemExit(main(p.parse_args()))
