"""One saved-video/model/SDK semantic delivery with child measurement."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    plan=read(HERE/'plan02.json');gate=read(HERE/'preflight_passed02.json')
    assert gate['passed'] and gate['plan_sha256']==sha(HERE/'plan02.json') and gate['tests_sha256']==sha(HERE/'windows_tests02.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    from qtpy.QtCore import QTimer,QEventLoop
    from qtpy.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel
    from ui.views.execution_view import ExecutionView
    from ui.ground_track import GroundChannelWidget
    from config.walking_config import WalkingConfig
    from client import SessionClient
    import links
    assert links.sdk_patch_installed, 'Use guarded entry01.py; native SDK is forbidden'
    from links import bind_client,sdk
    app=QApplication([]);assert app.platformName()=='windows';app.setQuitOnLastWindowClosed(False)
    stage=HERE/'runs02';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir()
    saved_argv=list(sys.argv)
    try:
        sys.argv=['read_context.py',str(stage/'gui_context.json')]
        runpy.run_path(str(ROOT/'experiments/qos_context_review/read_context.py'),run_name='__main__')
    finally:sys.argv=saved_argv
    launch_context=read(stage/'gui_context.json')
    assert launch_context['session_id']!=0 and launch_context['priority_class']==16384 and launch_context['qpa']=='windows'
    with (stage/'controller.json').open('x') as f:json.dump(dict(pid=os.getpid()),f)
    source=read(Path(plan['input_root'])/'report.json');meta=source['report_config_snapshot']
    cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
    expected={v['contact_id'] for v in source['walking_summary']['event_publications'] if v['active']}
    window=QWidget();window.setWindowTitle('IronJump 保存视频与SDK协议交付验证');window.resize(1450,900);window.setStyleSheet('background:#0d121a;color:#e0e0e0;')
    layout=QVBoxLayout(window);layout.addWidget(QLabel('保存视频 · 测量子进程 · 原生SDK模拟'))
    body=QHBoxLayout();layout.addLayout(body);view=ExecutionView();body.addWidget(view,4);body.addWidget(view._ground_track,1)
    view.configure(cfg);view._camera_start_timer.stop();panel=view._camera_panel;panel.setEnabled(True);panel.set_vision_enabled(True);panel._show_pose_action.setChecked(True);panel._chk_sdk_tracking.setChecked(True)
    for button in (view.btn_logi_camera,view.btn_tinyse_camera,view.btn_basic_camera):button.setEnabled(False)
    client=SessionClient(plan['input_root'],stage/'client');paints={};errors=[];reports=[];closed=[];paint_calls=0
    bind_client(client)
    assert panel._ensure_control();panel._preview_active=True;panel._start_vision();panel._preview_timer.start()
    import threading
    camera_stop=threading.Event();camera=dict(decoded_frames=0);video_threads=[];video_ids=[];draws=dict(all=0,valid=0,disabled_calls=0)
    original_submit=panel._submit_vision_frame
    def submit(frame,timing):video_ids.append(int(timing.frame_index));return original_submit(frame,timing)
    panel._submit_vision_frame=submit
    from ui.annotation_canvas import AnnotationCanvas
    original_draw=AnnotationCanvas._draw_live_pose
    from draw02 import paint_then_observe
    def draw(widget,painter,rect):return paint_then_observe(original_draw,widget,painter,rect,draws,errors)
    AnnotationCanvas._draw_live_pose=draw
    sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'))
    import enabled_replay
    def video():
        if client.clock.anchor_ns is None:QTimer.singleShot(10,video);return
        worker=threading.Thread(target=enabled_replay.replay_camera,args=(panel,client.clock,camera_stop,camera),daemon=True)
        video_threads.append(worker);worker.start()
    QTimer.singleShot(0,video)
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
    client.footprint_visual_frame.connect(view.on_footprint_visual_frame);client.device_message.connect(view.on_device_message)
    client.ready_boundary.connect(lambda key:client.start(acknowledge_quality=True,quality_key=key))
    client.source_drained.connect(client.stop);client.report_ready.connect(reports.append)
    view.stop_requested.connect(client.stop)
    def done(status):
        closed.append(status);QTimer.singleShot(250,app.quit)
    def failed(error):errors.append(error);app.quit()
    client.closed.connect(done);client.failed.connect(failed)
    def timeout():
        errors.append('gui_watchdog_timeout');client._fail('gui_watchdog_timeout')
    QTimer.singleShot(100000,timeout)
    window.show();QTimer.singleShot(0,client.prepare);app.exec();camera_stop.set()
    for worker in video_threads:worker.join(2)
    AnnotationCanvas._draw_live_pose=original_draw
    GroundChannelWidget.paintEvent=original_paint
    result=dict(complete=False,errors=errors,pid=os.getpid(),qt_platform=app.platformName(),expected_active_publications=sorted(expected),painted_active_publications=sorted(paints),paint_first_ns=paints,original_paint_calls=paint_calls,
        actor_pid=None if client.process is None else client.process.pid,actor_alive=client.process is not None and client.process.is_alive(),
        no_physical_camera_capture=panel._capture is None,saved_preview_replay=panel._preview_active,sdk=sdk,camera=camera,video_frame_ids=video_ids,draws=draws,
        performance_qualification=False,full_production_controller_compatibility=False,full_gui_load_qualification=False)
    try:
        assert not errors and len(closed)==len(reports)==1 and not result['actor_alive']
        assert client.state.phase=='complete' and not client.is_running
        assert set(paints)==expected and paint_calls>0
        assert result['no_physical_camera_capture'] and result['saved_preview_replay'] and camera['decoded_frames']>0 and draws['valid']>0 and draws['disabled_calls']==0
        assert all(not worker.is_alive() for worker in video_threads)
        sys.path.insert(0,str(ROOT/'experiments/consumer_session_delivery'));from verify import verify_values
        result['semantics']=verify_values(stage/'client/actor',ROOT)
        assert reports[0]==read(stage/'client/actor/report.json')
        assert sha(ROOT/'ui/ground_track.py')==plan['existing_sources']['ui/ground_track.py']
        result['complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        panel.shutdown();control=panel._closing_control
        if control is not None:
            loop=QEventLoop();control.closed.connect(loop.quit);QTimer.singleShot(6000,loop.quit);loop.exec()
        if panel._closing_control is not None or panel._control_stop_failed:result['errors'].append('SDKshutdown notconfirmed')
        result['complete']=result['complete'] and not result['errors']
        window.close()
        with (stage/'gui_result.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result),flush=True);raise SystemExit(not result['complete'])
