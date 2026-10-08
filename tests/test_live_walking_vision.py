from dataclasses import replace
from types import SimpleNamespace
import threading
import time

import numpy as np
import pytest

from vision.foot_reference import FootLabel, VisionConfig, VisionDecision
from vision.live_walking import LiveWalkingVision, classify_walking_contact, walking_check_text
from vision.service import EventHook, FootVisionService, PoseInferenceRecord
from vision.pose_overlay import build_pose_overlay
from tests.test_leg_identity import _sample
from tests.test_foot_reference import _sample as landing_sample


class Service:
    def __init__(self, *args, **kwargs):
        self.pose_inference_ready = EventHook()
        self.status_changed = EventHook()
        self.decision_ready = EventHook()
        self.frames = []
        self.metadata = []
        self.events = []
    def start(self):
        pass
    def stop(self):
        pass
    def submit_frame(self, frame, timestamp, *, metadata=None):
        self.frames.append(timestamp)
        self.metadata.append(metadata)
    def submit_touch_event(self, event_id, timestamp):
        self.events.append((event_id, timestamp))


def snapshot(i, contacts=(), stream='grid'):
    return {'device_timing': {'stream_id': stream, 'sample_time_s': i / 10,
                             'received_time_s': 100 + i / 10, 'frame_index': i * 100,
                             'origin_sample_time_s': 1.0},
            'walking': {'contacts': list(contacts)}}


def contact(i=0, start=.1, side='left'):
    return dict(id=i, start=start, side=side, confirmed=True, exclusion='')


def ready_vision():
    v = LiveWalkingVision(service_factory=Service, clock=lambda: 101.3)
    for i in range(35):
        v.submit_camera_frame(None, SimpleNamespace(sample_time_s=i / 25,
                              callback_time_s=100 + i / 25, frame_index=i))
    for i in range(12):
        v.submit_walking_snapshot(snapshot(i))
    return v


def test_live_check_uses_device_sample_clock_and_preserves_device_label():
    v = ready_vision()
    row = contact(side='right')
    v.submit_walking_snapshot(snapshot(12, [row]))
    event_id, timestamp = v._service.events[-1]
    assert timestamp == pytest.approx(101.1)
    v._service.decision_ready.emit(VisionDecision(event_id, FootLabel.LEFT, .99, 'landing', timestamp))
    _, _, check = v.display_state()
    assert check['label'] == 'left'
    assert '不一致' in walking_check_text(check)
    assert row['side'] == 'right'
    v.submit_walking_snapshot(snapshot(12, [row]))
    assert len(v._service.events) == 1


def test_unsynchronised_contact_is_unknown_and_never_queued():
    v = LiveWalkingVision(service_factory=Service)
    v.submit_walking_snapshot(snapshot(1, [contact()]))
    assert not v._service.events
    assert v.display_state()[2]['reason'] == 'clock_sync_unavailable'
    assert '无法核验' in walking_check_text(v.display_state()[2])


def test_old_stream_result_cannot_change_new_passage():
    v = ready_vision()
    v.submit_walking_snapshot(snapshot(12, [contact()]))
    old_id, timestamp = v._service.events[-1]
    v.submit_walking_snapshot(snapshot(1, [contact()], stream='new'))
    v._service.decision_ready.emit(VisionDecision(old_id, FootLabel.RIGHT, .99, 'landing', timestamp))
    assert v.display_state()[2]['label'] == 'unknown'


def test_camera_clock_degradation_rejects_inflight_result():
    v = ready_vision()
    v.submit_walking_snapshot(snapshot(12, [contact()]))
    event_id, timestamp = v._service.events[-1]
    v.submit_camera_frame(None, SimpleNamespace(sample_time_s=.1, callback_time_s=102, frame_index=1))
    v._service.decision_ready.emit(VisionDecision(event_id, FootLabel.LEFT, .99, 'landing', timestamp))
    assert v.display_state()[2]['label'] == 'unknown'


def test_pose_expires_missing_person_clears_and_stop_ignores_late_result():
    now = [1.1]
    v = LiveWalkingVision(service_factory=Service, clock=lambda: now[0])
    def emit(pose):
        v._service.pose_inference_ready.emit(PoseInferenceRecord(now[0], now[0], now[0], pose))
    emit(_sample(1.0));emit(_sample(1.1))
    assert '左腿' in v.display_state()[1]
    assert v.display_state()[0] is not None
    now[0] = 1.4
    assert v.display_state()[0] is None
    emit(None)
    assert '进入画面' in v.display_state()[1]
    v.stop();emit(_sample(1.4))
    assert v.display_state()[0] is None


@pytest.mark.parametrize('side', ['left','right'])
def test_ground_classifier_reuses_landing_motion_and_rejects_ambiguous_identity(side):
    samples = [replace(landing_sample(t, left_y=y if side=='left' else .84,
                       right_y=y if side=='right' else .84), identity_reject_reason='')
               for t,y in [(.82,.58),(.90,.68),(1.0,.82),(1.06,.83),(1.10,.83)]]
    result = classify_walking_contact(1, 1.0, samples, VisionConfig())
    assert result.label.value == side
    samples[2] = replace(samples[2], identity_reject_reason='legs_overlap')
    assert classify_walking_contact(1, 1.0, samples, VisionConfig()).label is FootLabel.UNKNOWN


def test_mirroring_moves_landmarks_without_swapping_anatomical_sides():
    normal = build_pose_overlay(_sample(1), 1000, 500)
    mirrored = build_pose_overlay(_sample(1), 1000, 500, mirrored=True)
    assert mirrored['nodes']['left_ankle']['point'][0] == 1000-normal['nodes']['left_ankle']['point'][0]
    assert mirrored['nodes']['left_ankle']['side'] == 'left'


def test_live_service_discards_pending_frames_during_slow_initialisation():
    entered, release = threading.Event(), threading.Event()
    seen = []
    class Adapter:
        def __init__(self, path):pass
        def open(self):entered.set();release.wait(2)
        def close(self):pass
        def infer_bgr(self, frame, timestamp):seen.append(frame);return None
    service = FootVisionService(VisionConfig(), 'unused', adapter_factory=Adapter, latest_frame_only=True)
    service.start()
    try:
        assert entered.wait(1)
        for i in range(100):service.submit_frame(i, i / 30)
        assert service.queue_depth['frames'] == 1
        release.set()
        deadline = time.perf_counter()+2
        while not seen and time.perf_counter()<deadline:time.sleep(.005)
        assert seen == [99]
    finally:release.set();service.stop()




def test_model_ready_recalibrates_clocks_after_startup_stall():
    v=ready_vision()
    v.submit_walking_snapshot(snapshot(12,[contact()]))
    event_id,timestamp=v._service.events[-1]
    v._service.status_changed.emit('ready')
    v._service.decision_ready.emit(VisionDecision(event_id,FootLabel.LEFT,.99,'landing',timestamp))
    assert v.display_state()[2]['label']=='unknown'
    assert v._camera_clock.snapshot.status.value=='warming_up'
    assert v._grid_clock.snapshot.status.value=='warming_up'


def test_clock_recovers_on_fresh_stable_window_without_accepting_old_events():
    v = ready_vision()
    v.submit_walking_snapshot(snapshot(12, [contact()]))
    old_id, old_time = v._service.events[-1]
    v.submit_camera_frame(None, SimpleNamespace(sample_time_s=.1, callback_time_s=102, frame_index=1))
    for i in range(60, 96):
        v.submit_camera_frame(None, SimpleNamespace(sample_time_s=i / 25,
                              callback_time_s=100 + i / 25, frame_index=i))
    assert v._camera_clock.snapshot.status.value == 'ready'
    v._service.decision_ready.emit(VisionDecision(old_id, FootLabel.LEFT, .99, 'landing', old_time))
    assert v.display_state()[2]['label'] == 'unknown'
    for i in range(13, 39):
        v.submit_walking_snapshot(snapshot(i))
    v.submit_walking_snapshot(snapshot(39, [contact(1, start=2.8)]))
    assert len(v._service.events) == 2
    assert all(a < b for a, b in zip(v._service.frames, v._service.frames[1:]))


@pytest.mark.parametrize('already_decided', [False, True])
def test_later_grid_exclusion_invalidates_visual_check(already_decided):
    v = ready_vision()
    v.submit_walking_snapshot(snapshot(12, [contact()]))
    event_id, timestamp = v._service.events[-1]
    decision = VisionDecision(event_id, FootLabel.LEFT, .99, 'landing', timestamp)
    if already_decided:
        v._service.decision_ready.emit(decision)
        assert v.display_state()[2]['label'] == 'left'
    rejected = {**contact(), 'exclusion': 'ambiguous_contacts'}
    v.submit_walking_snapshot(snapshot(13, [rejected]))
    v._service.decision_ready.emit(decision)
    check = v.display_state()[2]
    assert check['label'] == 'unknown'
    assert check['reason'] == 'contact_unavailable'
    assert not check.get('confidence')




def test_pending_touch_order_can_be_checked_when_order_resolves():
    v = ready_vision()
    v.submit_walking_snapshot(snapshot(12, [{**contact(), 'exclusion': 'pending_touch_order'}]))
    assert not v._service.events
    v.submit_walking_snapshot(snapshot(13, [{**contact(), 'exclusion': 'incomplete_contact'}]))
    assert len(v._service.events) == 1


def test_displayed_optical_side_tracks_later_identity_uncertainty():
    v = ready_vision()
    v.submit_walking_snapshot(snapshot(12, [contact()]))
    event_id, timestamp = v._service.events[-1]
    v._service.decision_ready.emit(VisionDecision(event_id, FootLabel.LEFT, .99, 'landing', timestamp))
    v.submit_walking_snapshot(snapshot(13, [contact(side='unknown')]))
    assert v.display_state()[2]['device_side'] == 'unknown'
    assert '一致' not in walking_check_text(v.display_state()[2])
