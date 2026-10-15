"""Same production reader inbox, session, ExecutionView and paint boundary; no subject storage."""
import argparse
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
from hardware.sensor_frame import DeviceLayout, SensorFrame
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

    def __init__(self, profile, **kwargs):
        super().__init__()
        self.profile = profile
        self.cancel = threading.Event()
        self.reader = None
        self.anchor_ns = None

    @Slot()
    def connect_device(self):
        self.device_state_changed.emit('connected', 'Offline source')

    @Slot()
    def prepare_walking_capture(self):
        self.start_capture()

    @Slot()
    def start_capture(self):
        if self.reader:return
        layout = DeviceLayout.linear(8)
        self.layout_detected.emit(layout)
        self.device_state_changed.emit('streaming', 'Offline source')
        def read():
            self.anchor_ns = time.perf_counter_ns()
            for n in range(8500):
                if self.cancel.wait(max(0, (self.anchor_ns+n*1000000-time.perf_counter_ns())/1e9)):return
                bits = np.zeros(768, dtype=np.uint8)
                for i in range(12):
                    onset = 3500+i*350
                    if onset <= n < onset+250:
                        low = 40+i*55
                        bits[low:low+21] = 1
                        if self.profile == 'mirror_fragment' and i == 0 and n >= onset+120:
                            bits[low+7:low+12] = 0
                wire = np.packbits(1-bits, bitorder='little')
                if self.profile == 'mirror_fragment' and n >= 3500 and n % 30 == 11:
                    wire[:32] = wire[64:]
                frame = SensorFrame('timing-offline', layout, n, n, time.perf_counter_ns(),
                                    layout.contact_bits(wire.tobytes()), b'\x01'*768, wire.tobytes())
                self.sensor_frame_received.emit(frame)
            self.exhausted.emit()
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    @Slot()
    def stop(self):
        self.cancel.set()
        if self.reader:self.reader.join(2)


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'protocol.json').write_text(json.dumps({'source':args.source,'mode':args.mode,'starting_foot':args.starting_foot,'duration_s':args.seconds,'p95_limit_ms':150,'max_limit_ms':250,'physical_ground_truth':'pending现场动作/录像核对'},ensure_ascii=False),encoding='utf-8')
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
    controller = SessionController(worker_factory=(lambda **kw:OfflineWorker(args.profile, **kw))
                                   if args.source == 'offline' else None)
    window = QWidget(); window.setWindowTitle('IronJump v1.15 isolated validation / '+args.mode)
    window.resize(1450,900); window.setStyleSheet('background:#0d121a;color:#e0e0e0;')
    outer=QVBoxLayout(window); banner=QLabel('Keep the lane clear until ready.');outer.addWidget(banner)
    body=QHBoxLayout();outer.addLayout(body)
    view=ExecutionView();body.addWidget(view,4);body.addWidget(view._ground_track,1)
    cfg=(WalkingConfig if args.mode=='walk' else OvergroundRunningConfig)(stop_type='Software command',starting_foot=args.starting_foot)
    view.configure(cfg);view._camera_start_timer.stop();view._camera_panel.set_vision_enabled(args.source=='usb')
    view._camera_panel.setEnabled(args.source=='usb')
    for b in (view.btn_logi_camera,view.btn_tinyse_camera,view.btn_basic_camera):b.setEnabled(args.source=='usb')
    view.set_quality_preflight_required(True)
    paint=GroundChannelWidget.paintEvent
    def measured_paint(widget,event):
        paint(widget,event)
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
        if status.get('ready') and not controller.is_running and started[0] is None:
            if status.get('requires_acknowledgement'):
                banner.setText('Degraded input: not armed. Keep lane clear.');return
            controller.start(quality_key=status['device_key'])
    def armed():
        started[0]=time.perf_counter_ns()
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
        payload=asdict(report)
        payload.pop('export_frames',None);payload.pop('export_timestamps',None)
        (args.output/'report.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
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
        def on_exhausted(self):QTimer.singleShot(200,lambda:controller.stop('manual'))
    delivery=Delivery()
    controller.walking_readiness_changed.connect(delivery.on_ready)
    view.start_requested.connect(delivery.on_start)
    controller.session_started.connect(delivery.on_armed)
    controller.footprint_visual_frame.connect(delivery.on_visual)
    controller.session_finished.connect(delivery.on_report)
    view.stop_requested.connect(delivery.on_stop)
    controller.prepare(cfg)
    worker=controller._worker
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
    QTimer.singleShot((args.seconds+240 if args.source=='usb' else 20)*1000,timeout)
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
    window.show();app.exec()
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
            row['scheduled_event_to_paint_ms']=(paints[cid]-worker.anchor_ns-row['touch_sample']*1000000)/1e6
    values=[r['received_to_paint_ms'] for r in rows.values() if 'received_to_paint_ms' in r]
    result={'source':args.source,'mode':args.mode,'profile':args.profile,'finished':finished[0],'errors':errors,
        'rows':list(rows.values()),'visual_frames':visuals,'filter_received_to_delivery_ms':{'p95':float(np.percentile(filtered_delays,95)) if filtered_delays else None,'max':max(filtered_delays,default=None)},
        'max_filter_held_frames':max(queue_sizes,default=0),'received_to_paint_ms':{'count':len(values),'p95':float(np.percentile(values,95)) if values else None,'max':max(values,default=None)},
        'scope':'Qt paint completion, not physical display scanout; hardware device and host clocks are not synchronized. Receipt-to-paint excludes unknown USB transit.',
        'provisional_receipt_to_paint_pass':bool(values and np.percentile(values,95)<=150 and max(values)<=250)}
    (args.output/'timing.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','visual_frames')},ensure_ascii=False),flush=True)
    factory.process=process;GroundChannelWidget.paintEvent=paint
    return int(not finished[0] or bool(errors))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',choices=('offline','usb'),default='offline')
    p.add_argument('--mode',choices=('walk','run'),default='walk');p.add_argument('--profile',choices=('normal','mirror_fragment'),default='normal')
    p.add_argument('--starting-foot',choices=('Not defined','Left','Right'),default='Not defined');p.add_argument('--seconds',type=int,default=30);p.add_argument('--output',type=Path,required=True)
    raise SystemExit(main(p.parse_args()))
