"""Run in the explicit vae vision + control worktree integration snapshot."""
from dataclasses import replace
import json
import sys
import time

import pytest
from qtpy.QtCore import QProcess
from ui.embedded_camera_panel import EmbeddedCameraPanel

from camera.control_service import CameraControlService
from camera.pose_transport import PoseRelay
from camera.tracking_runtime import TrackingRuntime
from tests.test_tracking_runtime import Sdk
from vision.foot_reference import Landmark
from vision.live_walking import LivePoseUpdate
from vision.service import EventHook, PoseFrameMetadata, PoseInferenceRecord


def pose_update(index=1, epoch=4, stamp=10.0):
    from tests.test_leg_identity import _sample
    pose = replace(_sample(stamp), landmarks_33=(Landmark(.8, .5, 0, .9, .9),) * 33)
    source = PoseFrameMetadata(index, .1, stamp, stamp+.02, 'ready', 1, epoch)
    record = PoseInferenceRecord(stamp, stamp+.02, stamp+.05, pose, frame_metadata=source)
    return LivePoseUpdate('pose', record)


def test_real_json_roundtrip_preserves_pose_provenance_and_reset_barrier():
    sdk, relay = Sdk(), PoseRelay()
    runtime = TrackingRuntime(sdk, lambda value: None, clock=lambda: 10.1)
    runtime.start(1)
    def send(update):
        relay.submit(update)
        packet = json.loads(json.dumps(relay.packet(1)))
        runtime.submit_packet(packet)
        runtime.tick()
        return packet
    first = send(pose_update(index=20))
    assert len(first['update']['inference']['pose']['landmarks_33']) == 33
    assert first['update']['inference']['frame_metadata']['callback_time_s'] == 10
    assert sdk.commands[-1][1] > 0
    # A late reset has its old origin. Coalescing it with no_pose and then a
    # current pose must preserve a stop without rejecting the current epoch.
    relay.submit(LivePoseUpdate('clock_reset', pose_update(index=99, epoch=2).inference))
    relay.submit(LivePoseUpdate('no_pose'))
    send(pose_update(index=21))
    assert sdk.commands[-1] == (0, 0)
    runtime.tick()
    assert sdk.commands[-1][1] > 0
    relay.submit(LivePoseUpdate('clock_reset'))
    send(pose_update(index=22))
    assert sdk.commands[-1] == (0, 0)
    runtime.tick()
    assert sdk.commands[-1][1] > 0
    old_callback = relay.submit
    old_callback(LivePoseUpdate('stopped'))
    send(pose_update(index=23))
    runtime.tick()
    assert sdk.commands[-1] == (0, 0)


def test_ui_sdk_mode_reuses_one_vision_and_never_auto_enables_builtin_ai(qtbot, monkeypatch):
    import vision.live_walking as module
    from ui.embedded_camera_panel import EmbeddedCameraPanel
    created, calls, callbacks = [], [], []
    class Vision:
        def __init__(self):
            self.pose_updates = EventHook()
            created.append(self)
        def start(self): pass
        def stop(self): self.pose_updates.emit(LivePoseUpdate('stopped'))
        def display_state(self): return object(), 'ready', None
    class Control:
        def request(self, *args): calls.append(args)
        def begin_tracking(self):
            calls.append(('tracking_start',))
            return callbacks.append
        def end_tracking(self): calls.append(('tracking_stop',))
        def close(self): pass
        def deleteLater(self): pass
    monkeypatch.setattr(module, 'LiveWalkingVision', Vision)
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel._control = Control()
    panel._preview_active = True
    panel._vision_enabled = True
    panel._start_vision()
    try:
        panel._chk_sdk_tracking.setChecked(True)
        panel._show_latest_frame()
        panel._on_ai_go()
        assert len(created) == 1
        assert calls == [('tracking_start',)]
        assert not panel._cmb_ai.isEnabled() and not panel._cmb_fov.isEnabled()
        created[0].pose_updates.emit(pose_update())
        assert len(callbacks) == 1
        panel._chk_sdk_tracking.setChecked(False)
        panel._show_latest_frame()
        assert calls == [('tracking_start',), ('tracking_stop',)]
        created[0].pose_updates.emit(pose_update(index=2))
        assert len(callbacks) == 1
        panel._on_ai_go()
        assert calls[-1] == ('set_ai_mode', 4)
    finally:
        panel.shutdown()


def fake_native_worker(tmp_path):
    script = tmp_path/'native_control.py'
    script.write_text('''import ctypes, json, os, sys, types
sys.path.insert(0, os.getcwd())
from camera.control_service import PREFIX, serve
def log(args):
 print(PREFIX+json.dumps({'tracking_log':{'fake_speed':list(args),'event':'fake_speed'}}),flush=True)
def speed(index,pitch,pan): log((pitch,pan)); return 0
def zoom(index,out): out._obj.value=1.; return 0
class Control:
 def __init__(self):
  self._idx=0
  self._dll=types.SimpleNamespace(obsbot_refresh_devices=lambda *a:1, obsbot_set_ai_mode=lambda *a:0,
   obsbot_set_fov=lambda *a:0,obsbot_set_zoom=lambda *a:0,obsbot_get_zoom=zoom,
   obsbot_set_gimbal_speed=speed,obsbot_get_gimbal_angles=lambda *a:0)
 def init(self): return True
 def set_ai_mode(self,*args): return 0
 def set_ai_off(self): return 0
 def close(self): pass
sys.modules['camera.tinyse_camera']=types.SimpleNamespace(TinySeCameraControl=Control)
raise SystemExit(serve())
''')
    return [sys.executable, '-u', str(script)]


def test_real_settings_process_transports_pose_expires_and_stops_on_eof(qtbot, tmp_path):
    service = CameraControlService(command=fake_native_worker(tmp_path))
    events, replies, failures = [], [], []
    service.tracking_event.connect(events.append)
    service.completed.connect(lambda *args: replies.append(args))
    service.failed.connect(failures.append)
    callback = service.begin_tracking()
    try:
        qtbot.waitUntil(lambda: ('tracking_start', 0) in replies, timeout=4000)
        callback(pose_update(stamp=time.perf_counter()))
        qtbot.waitUntil(lambda: any(row.get('fake_speed', [0,0])[1] > 0 for row in events), timeout=2000)
        count = len(events)
        qtbot.waitUntil(lambda: any(row.get('reason') == 'stale_frame' for row in events[count:]), timeout=2000)
        assert any(row['event'] == 'pose_input' for row in events)
        with pytest.raises(RuntimeError): service.request('set_ai_mode', 4)
        service.end_tracking()
        qtbot.waitUntil(lambda: ('tracking_stop', 0) in replies)
        callback(pose_update(index=2, stamp=time.perf_counter()))
        qtbot.wait(80)
    finally:
        service.close()
        qtbot.waitUntil(lambda: service._process.state() == QProcess.NotRunning, timeout=4000)
    assert not failures
    speeds = [row['fake_speed'] for row in events if 'fake_speed' in row]
    assert speeds[-1] == [0, 0]


def test_exit_without_sdk_stop_reply_is_reported(qtbot, tmp_path):
    script = tmp_path/'bad_exit.py'
    script.write_text('''import json,sys
print('IRON_CAMERA_CONTROL '+json.dumps({'ready':True}),flush=True)
for line in sys.stdin:
 r=json.loads(line)
 if 'method' in r:print('IRON_CAMERA_CONTROL '+json.dumps({'method':r['method'],'result':0}),flush=True)
''')
    service = CameraControlService(command=[sys.executable, '-u', str(script)])
    failures, replies = [], []
    service.failed.connect(failures.append)
    service.completed.connect(lambda *args: replies.append(args))
    service.begin_tracking()
    qtbot.waitUntil(lambda: ('tracking_start', 0) in replies, timeout=3000)
    service.close()
    qtbot.waitUntil(lambda: service._process.state() == QProcess.NotRunning)
    assert any('未收到 SDK 停止应答' in message for message in failures)


def test_replay_cancels_sdk_subscription_immediately(qtbot, monkeypatch):
    import vision.live_walking as module
    calls=[]
    class Vision:
        def __init__(self): self.pose_updates=EventHook()
        def start(self): pass
        def stop(self): pass
    class Control:
        def begin_tracking(self): calls.append('start'); return lambda value: None
        def end_tracking(self): calls.append('stop')
        def close(self): pass
        def deleteLater(self): pass
    monkeypatch.setattr(module, 'LiveWalkingVision', Vision)
    panel=EmbeddedCameraPanel(); qtbot.addWidget(panel)
    panel._control=Control(); panel._preview_active=True; panel._vision_enabled=True
    monkeypatch.setattr(panel._playback, 'open', lambda path: None)
    panel._chk_sdk_tracking.setChecked(True)
    try:
        assert calls == ['start']
        panel.open_recording('offline.avi')
        assert panel._replay_mode
        assert 'stop' in calls
        assert panel._pose_subscription is None
    finally: panel.shutdown()


def test_restart_waits_until_old_sdk_owner_finishes(qtbot, monkeypatch, tmp_path):
    import sys
    import camera.control_service as module
    script=tmp_path/'slow_exit.py'
    script.write_text('''import json,sys,time
print('IRON_CAMERA_CONTROL '+json.dumps({'ready':True}),flush=True)
for line in sys.stdin:
 r=json.loads(line)
 print('IRON_CAMERA_CONTROL '+json.dumps({'method':r['method'],'result':0}),flush=True)
time.sleep(.8)
''')
    created=[]; exited=set()
    class Control(CameraControlService):
        def __init__(self,parent=None):
            super().__init__(parent,command=[sys.executable,'-u',str(script)])
            created.append(self)
            self.closed.connect(lambda:exited.add(id(self)))
    monkeypatch.setattr(module,'CameraControlService',Control)
    panel=EmbeddedCameraPanel(); qtbot.addWidget(panel)
    monkeypatch.setattr(panel,'_start_capture',lambda:None)
    try:
        panel.start_preview()
        qtbot.waitUntil(lambda:created and created[0]._ready and not created[0]._busy and not created[0]._pending)
        previous=created[0]
        panel._restart_preview()
        assert previous._process.state() == QProcess.NotRunning or len(created) == 1
    finally:
        panel.shutdown()
        qtbot.waitUntil(lambda:all(id(item) in exited for item in created),timeout=4000)


def test_old_packet_cannot_be_retagged_when_mode_changes_during_log():
    from threading import Event,Thread
    from camera.pose_transport import PoseRelay
    from camera.tracking_runtime import TrackingRuntime
    from tests.test_sdk_tracking_integration import pose_update
    entered,release=Event(),Event()
    speeds=[]
    class Sdk:
        def disable_ai(self): pass
        def set_speed(self,pitch,pan):speeds.append((pitch,pan))
    def log(row):
        if row['event']=='pose_input':
            entered.set()
            assert release.wait(2)
    worker=TrackingRuntime(Sdk(),log,clock=lambda:10.1)
    worker.start(1)
    relay=PoseRelay(); relay.submit(pose_update())
    import json
    encoded=json.loads(json.dumps(relay.packet(1)))
    thread=Thread(target=worker.submit_packet,args=(encoded,))
    thread.start()
    try:
        assert entered.wait(1)
        worker.stop(); worker.start(2)
    finally:
        release.set(); thread.join(2)
    worker.tick()
    assert speeds[-1] == (0,0)
