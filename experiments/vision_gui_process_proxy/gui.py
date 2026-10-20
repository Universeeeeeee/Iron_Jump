"""One saved Walk GUI delivery with video decode and pose inference in a child."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];SESSION=ROOT/'experiments/session_gui_vision'
for folder in (ROOT,SESSION,HERE):sys.path.insert(0,str(folder))
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    plan=read(HERE/'plan01.json');gate=read(HERE/'preflight_passed01.json')
    assert gate['passed'] and gate['plan_sha256']==sha(HERE/'plan01.json') and gate['tests_sha256']==sha(HERE/'windows_tests01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    from qtpy.QtCore import QTimer,QEventLoop
    from qtpy.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel
    from ui.views.execution_view import ExecutionView
    from ui.ground_track import GroundChannelWidget
    from config.walking_config import WalkingConfig
    from client import SessionClient
    from proxy import VisionProcessProxy
    import links
    assert links.sdk_patch_installed
    from links import bind_client,sdk
    app=QApplication([]);assert app.platformName()=='windows';app.setQuitOnLastWindowClosed(False)
    stage=HERE/'runs01';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir()
    with (stage/'controller.json').open('x') as target:json.dump(dict(pid=os.getpid()),target)
    source=read(Path(plan['input_root'])/'report.json');meta=source['report_config_snapshot']
    cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
    expected={v['contact_id'] for v in source['walking_summary']['event_publications'] if v['active']}
    window=QWidget();window.setWindowTitle('IronJump 视频与模型子进程 GUI 交付门');window.resize(1450,900);window.setStyleSheet('background:#0d121a;color:#e0e0e0;')
    layout=QVBoxLayout(window);layout.addWidget(QLabel('保存 Walk · 原 GUI/绘图/SDK · 视频与模型子进程'))
    body=QHBoxLayout();layout.addLayout(body);view=ExecutionView();body.addWidget(view,4);body.addWidget(view._ground_track,1)
    view.configure(cfg);view._camera_start_timer.stop();panel=view._camera_panel;panel.setEnabled(True);panel._vision_enabled=True;panel._vision_label.show();panel._show_pose_action.setChecked(True);panel._chk_sdk_tracking.setChecked(True)
    for button in (view.btn_logi_camera,view.btn_tinyse_camera,view.btn_basic_camera):button.setEnabled(False)
    client=SessionClient(plan['input_root'],stage/'client');paints={};errors=[];reports=[];closed=[];paint_calls=0
    bind_client(client);assert panel._ensure_control();panel._preview_active=True
    vision=VisionProcessProxy(plan,stage/'vision',panel._queue_preview_frame);panel._vision=vision;panel._connect_sdk_tracking();vision.start();panel._preview_timer.start()
    from ui.annotation_canvas import AnnotationCanvas
    original_draw=AnnotationCanvas._draw_live_pose
    from draw02 import paint_then_observe
    draws=dict(all=0,valid=0,disabled_calls=0)
    def draw(widget,painter,rect):return paint_then_observe(original_draw,widget,painter,rect,draws,errors)
    AnnotationCanvas._draw_live_pose=draw
    assert GroundChannelWidget.paintEvent.__module__=='ui.ground_track'
    original_paint=GroundChannelWidget.paintEvent
    def paint(widget,event):
        global paint_calls
        original_paint(widget,event)
        if widget is view._ground_track.channel:
            paint_calls+=1
            for foot in widget._feet+widget.history:
                cid=foot.get('contact_id')
                if cid in expected and cid not in paints and foot.get('status')=='confirmed':paints[cid]=time.perf_counter_ns()
    GroundChannelWidget.paintEvent=paint
    client.device_state_changed.connect(view.on_device_state);client.device_layout_changed.connect(view.on_device_layout)
    client.walking_readiness_changed.connect(view.on_walking_readiness);client.beam_quality_notice.connect(view.on_beam_quality_notice)
    client.session_started.connect(view.on_session_started);client.gait_snapshot.connect(view.on_gait_snapshot)
    client.gait_snapshot.connect(panel.on_walking_snapshot);client.footprint_visual_frame.connect(view.on_footprint_visual_frame);client.device_message.connect(view.on_device_message)
    client.ready_boundary.connect(lambda key:client.start(acknowledge_quality=True,quality_key=key));client.source_drained.connect(client.stop);client.report_ready.connect(reports.append)
    view.stop_requested.connect(client.stop)
    def done(status):
        closed.append(status)
        def settle():
            if vision.result is None:QTimer.singleShot(100,settle)
            else:app.quit()
        QTimer.singleShot(0,settle)
    def failed(error):errors.append(error);app.quit()
    client.closed.connect(done);client.failed.connect(failed)
    def timeout():errors.append('gui_watchdog_timeout');client._fail('gui_watchdog_timeout');app.quit()
    QTimer.singleShot(210000,timeout)
    window.show();QTimer.singleShot(0,client.prepare);app.exec()
    if vision.receiver is not None:vision.receiver.join(2)
    AnnotationCanvas._draw_live_pose=original_draw;GroundChannelWidget.paintEvent=original_paint
    if vision.result is not None and vision.errors:errors.extend(vision.errors)
    result=dict(complete=False,errors=errors,pid=os.getpid(),qt_platform=app.platformName(),expected_active_publications=sorted(expected),painted_active_publications=sorted(paints),paint_first_ns=paints,original_paint_calls=paint_calls,
        measurement_pid=None if client.process is None else client.process.pid,measurement_alive=client.process is not None and client.process.is_alive(),
        vision_receiver_alive=vision.receiver is not None and vision.receiver.is_alive(),
        no_physical_camera_capture=panel._capture is None,saved_preview_replay=panel._preview_active,sdk=sdk,vision=vision.result,
        video_frame_ids=vision.preview_ids,pose_ordinals=vision.pose_ordinals,draws=draws,actual_camera_recording_qualified=False,performance_qualification=False,field_fix_verified=False)
    try:
        assert not errors and len(closed)==len(reports)==1 and not result['measurement_alive']
        assert client.state.phase=='complete' and not client.is_running and vision.complete and not vision.result['child_alive'] and not result['vision_receiver_alive']
        assert set(paints)==expected and paint_calls>0 and result['no_physical_camera_capture'] and draws['valid']>0 and draws['disabled_calls']==0
        assert len(vision.preview_ids)==plan['counts']['preview_frames'] and vision.pose_ordinals==list(range(plan['counts']['inferences']))
        sys.path.insert(0,str(ROOT/'experiments/consumer_session_delivery'));from verify import verify_values
        result['semantics']=verify_values(stage/'client/actor',ROOT);assert reports[0]==read(stage/'client/actor/report.json')
        result['complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        panel.shutdown();control=panel._closing_control
        if control is not None:
            loop=QEventLoop();control.closed.connect(loop.quit);QTimer.singleShot(6000,loop.quit);loop.exec()
        if panel._closing_control is not None or panel._control_stop_failed:result['errors'].append('SDK shutdown not confirmed')
        result['complete']=result['complete'] and not result['errors'];window.close()
        with (stage/'gui_result.json').open('x') as target:json.dump(result,target,indent=2)
    print(json.dumps(dict(complete=result['complete'],errors=result['errors'],pids=dict(gui=result['pid'],measurement=result['measurement_pid'],vision=vision.result['child_pid']),previews=len(vision.preview_ids),poses=len(vision.pose_ordinals),draws=draws,sdk=sdk)),flush=True)
    raise SystemExit(not result['complete'])
