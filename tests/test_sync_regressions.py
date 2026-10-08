"""Regression contracts reproduced during the offline sync review."""


import json


import pytest


from tests.test_walking_vision_pipeline import landing_pose


from vision.event_scheduler import EventWindowScheduler


from vision.foot_reference import FootLabel, VisionConfig


from vision.live_walking import classify_walking_contact


def evidence(record_property, **values):
    record_property('evidence', json.dumps(values, ensure_ascii=False))


def scheduler(max_frames=40):
    return EventWindowScheduler(VisionConfig(
        pre_event_ms=150, post_event_ms=150, inference_interval_ms=50,
        decision_timeout_ms=450, frame_buffer_ms=1000, max_frames=max_frames))


def prime(s):
    for ms in range(500, 1151, 50):
        s.add_frame(None, ms / 1000)
        assert not s.process_ready(lambda _, t: landing_pose(t),
                                   classify_walking_contact, now_s=ms / 1000)
    cached = [p for t, p in s._pose_cache.items() if 850 <= t <= 1150]
    assert classify_walking_contact(1, 1., cached, s.config).label is FootLabel.LEFT


def test_complete_pose_cache_survives_raw_image_eviction(record_property):
    s = scheduler(20)
    prime(s)
    for ms in range(1160, 1301, 10):
        s.add_frame(None, ms / 1000)
    s.add_event(1, 1., submitted_at_s=1.3)
    result = s.process_ready(lambda _, t: landing_pose(t), classify_walking_contact, now_s=1.3)[0]
    evidence(record_property, oldest_image_s=s._frames[0].captured_at_s,
             cached_window_poses=result.diagnostics.pose_total, label=result.label.value,
             reason=result.reason, submitted_age_ms=300, deadline_age_ms=450)
    assert result.label is FootLabel.LEFT, result


def test_high_rate_frames_do_not_expire_an_ontime_event(record_property):
    s = scheduler(20)
    decisions = []
    for ms in range(500, 1151, 10):
        s.add_frame(None, ms / 1000)
        if ms == 1000:
            s.add_event(1, 1., submitted_at_s=1.)
        decisions.extend(s.process_ready(lambda _, t: landing_pose(t),
                                         classify_walking_contact, now_s=ms / 1000))
    evidence(record_property, label=decisions[0].label.value, reason=decisions[0].reason,
             decided_at_s=decisions[0].decided_at_s)
    assert decisions[0].label is FootLabel.LEFT, decisions[0]


def test_ready_event_is_decided_before_unrelated_inference(record_property):
    s = scheduler()
    prime(s)
    s.add_event(1, 1., submitted_at_s=1.43)
    s.add_frame(None, 1.43)
    now = [1.43]
    def infer(_, ms):
        now[0] += .03
        return landing_pose(ms)
    result = s.process_ready(infer, classify_walking_contact, now_s=now[0],
                             decision_clock=lambda: now[0])[0]
    evidence(record_property, label=result.label.value, reason=result.reason,
             decided_at_s=result.decided_at_s, actual_finish_s=now[0])
    assert result.label is FootLabel.LEFT, result
    assert result.decided_at_s <= 1.45


def test_classifier_completion_must_meet_deadline(record_property):
    s = scheduler()
    prime(s)
    s.add_event(1, 1., submitted_at_s=1.44)
    now = [1.44]
    def classify(*args):
        result = classify_walking_contact(*args)
        now[0] += .02
        return result
    result = s.process_ready(lambda _, t: landing_pose(t), classify,
                             now_s=now[0], decision_clock=lambda: now[0])[0]
    evidence(record_property, label=result.label.value, reason=result.reason,
             recorded_decision_s=result.decided_at_s, actual_finish_s=now[0])
    assert result.label is FootLabel.UNKNOWN, result
    assert result.reason == 'decision_timeout'
    assert result.decided_at_s >= 1.46


@pytest.mark.parametrize('fault', ['late', 'missing'])
def test_unusable_evidence_remains_unknown(fault):
    s = scheduler()
    for ms in range(500, 1151, 50):
        s.add_frame(None, ms / 1000)
    now = 1.6 if fault == 'late' else 1.3
    s.add_event(1, 1., submitted_at_s=now)
    result = s.process_ready(lambda _, t: None if fault == 'missing' else landing_pose(t),
                             classify_walking_contact, now_s=now)[0]
    assert result.label is FootLabel.UNKNOWN
    assert result.reason == ('decision_timeout' if fault == 'late' else 'pose_window_unavailable')


def test_ready_decision_returns_before_unrelated_inference_can_block():
    s = scheduler()
    prime(s)
    s.add_event(1, 1., submitted_at_s=1.43)
    s.add_frame(None, 1.43)
    inferred = []
    result = s.process_ready(lambda _, ms: inferred.append(ms), classify_walking_contact, now_s=1.43)
    assert result[0].label is FootLabel.LEFT
    assert not inferred
    assert not s.process_ready(lambda _, ms: inferred.append(ms), classify_walking_contact, now_s=1.44)
    assert inferred == [1430]


def test_raw_frames_without_pose_history_cannot_synthesize_missing_evidence():
    s = scheduler(20)
    # A whole camera batch arrives late; the evicted input frames were never inferred.
    for ms in range(500, 1301, 10):
        s.add_frame(None, ms / 1000)
    s.add_event(1, 1., submitted_at_s=1.3)
    result = s.process_ready(lambda _, ms: landing_pose(ms), classify_walking_contact, now_s=1.3)[0]
    assert result.label is FootLabel.UNKNOWN
