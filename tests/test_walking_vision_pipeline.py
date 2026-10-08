"""Exercise ordered raw Pose -> scheduler -> walking classifier, without hand-set identity tags."""
from dataclasses import replace

import pytest

from tests.test_leg_identity import _sample
from vision.event_scheduler import EventWindowScheduler
from vision.foot_reference import FootLabel, VisionConfig
from vision.live_walking import classify_walking_contact


def landing_pose(timestamp_ms, side='left'):
    sample = _sample(timestamp_ms / 1000)
    y = .58 if timestamp_ms <= 850 else min(.83, .58 + (timestamp_ms - 850) / 150 * .25)
    return replace(sample, **{f'{side}_{joint}': replace(getattr(sample, f'{side}_{joint}'), y=y)
                              for joint in ('ankle', 'heel', 'foot_index')})


def run_window(missing=(), side='left', transform=lambda sample: sample):
    config = VisionConfig(pre_event_ms=150, post_event_ms=150, inference_interval_ms=50,
                          decision_timeout_ms=450, max_frames=40)
    scheduler = EventWindowScheduler(config)
    decisions = []
    for stamp in range(500, 1200, 50):
        scheduler.add_frame(None, stamp / 1000)
        if stamp == 1000:
            scheduler.add_event(1, 1.0, submitted_at_s=1.0)
        decisions.extend(scheduler.process_ready(
            lambda _, ms: None if ms in missing else transform(landing_pose(ms, side)),
            classify_walking_contact, now_s=stamp / 1000))
    return decisions[0]


@pytest.mark.parametrize('side', ['left', 'right'])
def test_raw_pose_reaches_walking_classifier_with_scheduler_identity_tags(side):
    assert landing_pose(1000, side).identity_reject_reason is None
    assert run_window(side=side).label.value == side


def test_person_missing_at_landing_is_not_accepted_from_surrounding_frames():
    decision = run_window(missing=(950, 1000))
    assert decision.label is FootLabel.UNKNOWN


def test_missing_person_requires_recovery_without_forgetting_trusted_sides():
    from vision.leg_identity import LegIdentityAnalyzer
    analyzer = LegIdentityAnalyzer()
    analyzer.update(_sample(.5))
    assert analyzer.update(_sample(.55)).state.value == 'stable'
    assert analyzer.update(None).state.value == 'unavailable'
    # An initial swap after reappearance must not become the new trusted identity.
    assert analyzer.update(_sample(.65, left_x=.65, right_x=.35)).state.value == 'ambiguous'
    states = [analyzer.update(_sample(t)).state.value for t in (.7, .75, .8)]
    assert states == ['ambiguous', 'ambiguous', 'stable']


@pytest.mark.parametrize('fault', ['low_quality', 'overlap', 'label_swap'])
def test_walking_window_rejects_uncertain_raw_pose(fault):
    def transform(sample):
        if sample.timestamp_s < .95:
            return sample
        changes = {}
        for side, other in (('left', 'right'), ('right', 'left')):
            for joint in ('hip', 'knee', 'ankle', 'heel', 'foot_index'):
                name = f'{side}_{joint}'
                point = getattr(sample, name)
                if fault == 'low_quality':
                    changes[name] = replace(point, visibility=.2, presence=.2)
                elif fault == 'overlap':
                    changes[name] = replace(getattr(sample, f'left_{joint}'),
                                            x=.5 if side == 'left' else .51)
                else:
                    changes[name] = getattr(sample, f'{other}_{joint}')
        return replace(sample, **changes)

    decision = run_window(transform=transform)
    assert decision.label is FootLabel.UNKNOWN
    assert decision.reason == 'identity_ambiguous'


def test_missing_camera_frames_at_touch_do_not_bridge_blind_interval():
    scheduler = EventWindowScheduler(VisionConfig(
        pre_event_ms=150, post_event_ms=150, inference_interval_ms=50,
        decision_timeout_ms=450, max_frames=40))
    decisions = []
    for stamp in range(500, 1200, 50):
        if stamp not in (950, 1000):
            scheduler.add_frame(None, stamp / 1000)
        if stamp == 1000:
            scheduler.add_event(1, 1.0, submitted_at_s=1.0)
        decisions.extend(scheduler.process_ready(
            lambda _, ms: landing_pose(ms), classify_walking_contact, now_s=stamp / 1000))
    assert decisions[0].label is FootLabel.UNKNOWN
    assert decisions[0].reason == 'pose_gap_exceeded'
