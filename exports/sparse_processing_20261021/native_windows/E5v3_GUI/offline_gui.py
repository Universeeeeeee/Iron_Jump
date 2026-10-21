"""Original process+batch40 and ExecutionView, with saved optics/video only."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
if os.name=='nt':
    os.environ.setdefault('QT_QPA_FONTDIR','C:/Windows/Fonts')
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--variant',choices=('baseline','combined'),required=True)
    parser.add_argument('--features',default='')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    os.environ['IRON_OFFLINE_VARIANT']=args.variant
    os.environ['IRON_SPARSE_FEATURES']=args.features
    import cv2
    import qtpy
    import numpy as np
    from qtpy.QtCore import QTimer
    from qtpy.QtWidgets import QApplication,QWidget,QHBoxLayout
    from config.walking_config import WalkingConfig
    from ui.embedded_camera_panel import EmbeddedCameraPanel
    from ui.views.execution_view import ExecutionView
    from ui.ground_track import GroundChannelWidget
    import bootstrap
    bootstrap.fences()
    EmbeddedCameraPanel.start_preview=bootstrap.forbidden('physical camera preview')
    from client import LiveSessionProcess
    from analyze_walk import queue_bound
    errors=[];sys.excepthook=lambda kind,value,tb:errors.append(repr(value))
    app=QApplication([])
    meta=json.loads((args.fixture/'report.json').read_text(encoding='utf-8'))['report_config_snapshot']
    cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__
                         and WalkingConfig.__dataclass_fields__[k].init})
    view=ExecutionView();view.configure(cfg);view._camera_start_timer.stop()
    panel=view._camera_panel;panel.set_vision_enabled(False)
    # Only saved decoded images enter the existing preview/render path.
    panel._preview_active=True;panel._preview_timer.start()
    window=QWidget();layout=QHBoxLayout(window);layout.addWidget(view)
    layout.addWidget(view._ground_track);window.resize(1450,900);window.show()
    client=LiveSessionProcess(args.output/'client',batch_size=40,fixture_root=str(args.fixture))
    paints={};visuals={};started=[];closed=[];reports=[];status={};stop_ns=[]
    original_paint=GroundChannelWidget.paintEvent
    def paint(widget,event):
        original_paint(widget,event)
        if widget is view._ground_track.channel:
            now=time.perf_counter_ns()
            for foot in widget._feet+widget.history:
                if foot.get('status')=='confirmed' and foot.get('contact_id') is not None:
                    paints.setdefault(str(foot['contact_id']),now)
    GroundChannelWidget.paintEvent=paint
    client.device_state_changed.connect(view.on_device_state)
    client.device_layout_changed.connect(view.on_device_layout)
    client.walking_readiness_changed.connect(view.on_walking_readiness)
    client.session_started.connect(view.on_session_started)
    client.gait_snapshot.connect(view.on_gait_snapshot)
    client.footprint_visual_frame.connect(view.on_footprint_visual_frame)
    client.beam_quality_notice.connect(view.on_beam_quality_notice)
    def visual(frame):
        for f in frame.get('feet',[]):
            if f.get('status')=='confirmed':visuals.setdefault(str(f['contact_id']),time.perf_counter_ns())
    client.footprint_visual_frame.connect(visual)
    def ready(value):
        if (value.get('ready') and value.get('_sparse_processed_sample')==meta['device']['checked_sample_index']
                and not started and not client._start_pending):
            client.start(acknowledge_quality=True,quality_key=value['device_key'])
    client.walking_readiness_changed.connect(ready)
    with np.load(args.fixture/'raw_frames.npz') as raw:
        index=int(np.searchsorted(raw['sample_indices'],meta['device']['checked_sample_index']))
        original_checked=int(raw['received_ns'][index])
    record_start=json.loads((args.fixture/'camera_record_start.json').read_text())['host_ns']
    with (args.fixture/'camera.csv').open() as stream:video=list(csv.DictReader(stream))
    selected=[];previous=-1
    for row in video:
        t=float(row['record_elapsed_seconds'])
        if record_start+round(t*1e9)<original_checked or t-previous<1/30:continue
        selected.append((record_start+round(t*1e9)-original_checked,row));previous=t
    source=(args.fixture/'camera.mjpg').open('rb')
    video_stats={'decoded_frames':0,'discarded_due_frames':0,'expected_due_frames':0,
                 'displayed_frames':0,'max_decode_lateness_ms':0}
    anchor=None;video_thread=None;video_cancel=threading.Event()
    mirror_saved_video=panel._chk_mirror.isChecked()
    original_on_frame=panel._on_frame
    def on_preview_frame(frame):
        original_on_frame(frame)
        video_stats['displayed_frames']+=1
    panel._on_frame=on_preview_frame
    def read_video():
        try:
            for due,row in selected:
                if video_cancel.wait(max(0,(anchor+due-time.perf_counter_ns())/1e9)):
                    return
                video_stats['expected_due_frames']+=1
                source.seek(int(row['offset']));data=source.read(int(row['length']))
                image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
                if image is None:raise RuntimeError('Saved JPEG decode failed')
                if mirror_saved_video:image=cv2.flip(image,1)
                panel._queue_preview_frame(image)
                video_stats['decoded_frames']+=1
                video_stats['max_decode_lateness_ms']=max(video_stats['max_decode_lateness_ms'],
                    (time.perf_counter_ns()-anchor-due)/1e6)
        except BaseException as exc:
            errors.append('saved_video:'+repr(exc))
    def armed():
        nonlocal anchor,video_thread
        started.append(time.perf_counter_ns());anchor=started[-1]
        video_thread=threading.Thread(target=read_video,name='SavedJPEGReplay')
        video_thread.start()
    client.session_started.connect(armed)
    def stop():
        stop_ns.append(time.perf_counter_ns());video_cancel.set();client.stop('manual')
    client.source_exhausted.connect(lambda:QTimer.singleShot(250,stop))
    client.session_finished.connect(reports.append)
    client.closed.connect(lambda value:(closed.append(value),app.quit()))
    client.failed.connect(lambda value:(errors.append(value),app.quit()))
    client.prepare(cfg)
    QTimer.singleShot(120000,lambda:(errors.append('offline timeout'),app.quit()))
    app.exec()
    if errors:
        if not client.finalize_failure(10) and client.process is not None:
            client.process.terminate();client.process.join(10)
            errors.append('forced offline actor cleanup')
    video_cancel.set()
    if video_thread is not None:
        video_thread.join(5)
        if video_thread.is_alive():errors.append('saved_video_thread_still_alive')
    video_was_visible=panel._display_frame is not None
    vision_was_active=panel._vision is not None
    if video_thread is None or not video_thread.is_alive():source.close()
    panel._preview_active=False;panel.shutdown()
    window.hide();GroundChannelWidget.paintEvent=original_paint
    assert client.process is None or not client.process.is_alive(),'Offline actor still alive'
    actor_folder=args.output/'client/actor'
    if not (actor_folder/'result.json').exists():
        result={'complete':False,'errors':errors,'hardware_attempts':bootstrap.HARDWARE_ATTEMPTS}
    else:
        actor=json.loads((actor_folder/'result.json').read_text())
        report=json.loads((actor_folder/'report.json').read_text()) if (actor_folder/'report.json').exists() else {}
        with np.load(actor_folder/'raw_frames.npz') as raw:
            indices=raw['sample_indices'];receipts={int(n):int(t) for n,t in zip(indices,raw['received_ns'])}
            contiguous=bool(np.array_equal(indices,np.arange(int(indices[0]),int(indices[-1])+1)))
            raw_sha=hashlib.sha256(raw['bits'].tobytes()+raw['wire'].tobytes()).hexdigest()
        rows=sorted(actor['queue_common']+actor['queue_samples']+([actor['queue_final']] if actor['queue_final'] else []),key=lambda r:r[0])
        queue_valid,upper=queue_bound(rows,int(indices[0]),int(indices[-1]))
        events=report.get('walking_summary',{}).get('event_publications',[])
        latencies=[];event_rows=[]
        for event in events:
            if not event['active']:continue
            cid=str(event['contact_id']);receipt=receipts.get(event['touch_sample']);paint=paints.get(cid)
            latency=None if receipt is None or paint is None else (paint-receipt)/1e6
            if latency is not None:latencies.append(latency)
            event_rows.append({'contact_id':cid,'touch_sample':event['touch_sample'],
                'receipt_to_paint_ms':latency,'paint_before_stop':bool(paint and stop_ns and paint<stop_ns[0])})
        result={'complete':not errors and len(started)==len(closed)==len(reports)==1 and closed[0]['complete']
                          and actor['complete'] and contiguous and queue_valid,
            'errors':errors,'actor_pid':actor['pid'],'raw_sha256':raw_sha,'queue_bound_valid':queue_valid,
            'unfinished_upper_bound':upper,'events':event_rows,'video':video_stats,
            'hardware_attempts':bootstrap.HARDWARE_ATTEMPTS,'batch_size':actor['batch_size'],
            'worker_class':actor['worker_class'],'live_default_USB':actor['live_default_USB'],
            'max_contact_to_paint_ms':max(latencies,default=None),
            'p95_contact_to_paint_ms':float(np.percentile(latencies,95)) if latencies else None,
            'all_contacts_painted_before_stop':bool(event_rows) and all(r['paint_before_stop'] for r in event_rows),
            'prepared_sample':report.get('report_config_snapshot',{}).get('device',{}).get('checked_sample_index'),
            'expected_prepared_sample':meta['device']['checked_sample_index'],
            'qt_platform':app.platformName(),'dpr':window.devicePixelRatioF(),
            'qt_api':qtpy.API_NAME,'qt_version':qtpy.QT_VERSION,
            'font_directory':os.environ.get('QT_QPA_FONTDIR'),
            'view_size':[view.width(),view.height()],
            'saved_video_visible':video_was_visible,
            'pose_worker_started':vision_was_active,
            'scope':'Original process+batch40 and ExecutionView, offscreen Qt paint completion, saved video only. No SDK/pose inference, hardware or human acceptance.'}
        result['complete'] &= (not result['hardware_attempts'] and not result['live_default_USB']
                               and result['prepared_sample']==result['expected_prepared_sample']
                               and not vision_was_active and video_was_visible
                               and video_stats['expected_due_frames']>=100
                               and video_stats['decoded_frames']>=.90*video_stats['expected_due_frames'])
        result['performance_pass']=bool(result['complete'] and upper<=250
            and result['all_contacts_painted_before_stop'] and latencies
            and max(latencies)<=250 and np.percentile(latencies,95)<=150)
    (args.output/'offline_result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    return int(not result['complete'])


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    try:result=main()
    except Exception:
        import traceback
        traceback.print_exc();raise SystemExit(1)
    raise SystemExit(result)
