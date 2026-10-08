from dataclasses import replace
import math
import time
from types import SimpleNamespace

import pytest

from camera.gimbal_control import SpeedWatchdog
from vision.gimbal_tracking import TrackingSpeeds, full_body_target, tracking_velocity


def test_horizontal_response_is_faster_and_axes_independent():
    pitch, pan = tracking_velocity((.8, .8))
    assert pan == pytest.approx(57.6)
    assert pitch == pytest.approx(19.2)
    assert tracking_velocity((.8, .5)) == pytest.approx((0, 57.6))
    assert tracking_velocity((.5, .8)) == pytest.approx((19.2, 0))
    assert tracking_velocity((0, 1)) == (30, -90)


@pytest.mark.parametrize('target', [None, (.5, .5), (.53, .47), (math.nan, .8), (1.1, .5)])
def test_missing_invalid_and_centered_targets_stop(target):
    assert tracking_velocity(target) == (0, 0)


def test_direction_can_be_corrected_without_changing_gain():
    pitch, pan = tracking_velocity((.8, .8))
    assert tracking_velocity((.8, .8), TrackingSpeeds(pan_sign=-1, pitch_sign=-1)) == (-pitch, -pan)


@pytest.mark.parametrize('kwargs', [{'pan_max': 181}, {'pitch_max': 91}, {'pan_gain': math.nan},
                                   {'pitch_gain': -1}, {'deadzone': .5}, {'pan_sign': 0}])
def test_invalid_speed_settings_rejected(kwargs):
    with pytest.raises(ValueError):
        TrackingSpeeds(**kwargs)


def test_target_includes_head_hands_and_feet_and_rejects_missing_body():
    from vision.foot_reference import Landmark
    point = Landmark(.7, .4, 0, .9, .9)
    points = [point] * 33
    points[0] = replace(point, y=.1)
    points[16] = replace(point, x=.9, y=.2)
    points[31] = replace(point, x=.6, y=.9)
    pose = SimpleNamespace(landmarks_33=tuple(points))
    assert full_body_target(pose) == pytest.approx((.75, .5))
    # An occluded hand is ignored; missing core body/ankles stops motion.
    points[16] = replace(points[16], visibility=.2)
    pose.landmarks_33 = tuple(points)
    assert full_body_target(pose) == pytest.approx((.65, .5))
    points[27] = replace(point, visibility=.2)
    pose.landmarks_33 = tuple(points)
    assert full_body_target(pose) is None
    assert full_body_target(SimpleNamespace(landmarks_33=None)) is None
    assert full_body_target(None) is None


@pytest.mark.parametrize('field', ['visibility', 'presence'])
@pytest.mark.parametrize('value', [math.nan, math.inf, 1.2])
def test_target_rejects_invalid_individual_confidence(field, value):
    from vision.foot_reference import Landmark
    point = Landmark(.7, .4, 0, .9, .9)
    points = [point] * 33
    points[11] = replace(point, **{field: value})
    assert full_body_target(SimpleNamespace(landmarks_33=tuple(points))) is None


class FakeSdk:
    def __init__(self):
        self.commands = []
        self.disabled = False

    def disable_ai(self):
        self.disabled = True

    def set_speed(self, pitch, pan):
        assert self.disabled
        self.commands.append((pitch, pan))


def wait_for(predicate):
    deadline = time.perf_counter() + 2
    while not predicate() and time.perf_counter() < deadline:
        time.sleep(.01)
    assert predicate()


def test_watchdog_stops_if_inference_stalls_and_on_close():
    sdk = FakeSdk()
    control = SpeedWatchdog(sdk, timeout=.12)
    control.start()
    try:
        control.update(10, 60, time.perf_counter())
        wait_for(lambda: (10, 60) in sdk.commands)
        wait_for(lambda: sdk.commands[-1] == (0, 0))
        control.update(10, 90, time.perf_counter() - 1)
        time.sleep(.08)
        assert (10, 90) not in sdk.commands
        control.update(5, 30, time.perf_counter())
        wait_for(lambda: (5, 30) in sdk.commands)
    finally:
        control.close()
    assert sdk.commands[-1] == (0, 0)


def test_stop_cancels_pending_motion():
    sdk = FakeSdk()
    control = SpeedWatchdog(sdk)
    control.start()
    try:
        control.update(0, 60, time.perf_counter())
        control.stop_motion()
        count = len(sdk.commands)
        time.sleep(.12)
        assert all(command == (0, 0) for command in sdk.commands[count:])
        with pytest.raises(ValueError):
            control.update(0, math.nan, time.perf_counter())
    finally:
        control.close()


def test_watchdog_reports_sdk_failure_and_attempts_stop():
    class FailingSdk(FakeSdk):
        def set_speed(self, pitch, pan):
            super().set_speed(pitch, pan)
            if pan:
                raise RuntimeError('disconnected')

    sdk = FailingSdk()
    control = SpeedWatchdog(sdk)
    control.start()
    control.update(0, 60, time.perf_counter())
    wait_for(lambda: control.error is not None)
    with pytest.raises(RuntimeError, match='stop/control failed'):
        control.close()
    assert sdk.commands[-1] == (0, 0)


@pytest.mark.parametrize('failure', ['start', 'pulse'])
def test_validator_stops_gimbal_and_closes_capture_on_failure(monkeypatch, tmp_path, failure):
    import json
    from camera import tinyse_dshow_capture
    from tools import tinyse_gimbal_validator as tool

    sdk = FakeSdk()
    sdk.angles = lambda: {'return_code': 0, 'roll_pitch_pan': [0, 0, 0]}
    calls = []

    class Capture:
        def __init__(self, on_timed_frame):
            on_timed_frame(b'jpeg', 0, 0, time.perf_counter())

        def start(self):
            if failure == 'start':
                raise RuntimeError('start failed')

        def start_record(self, path):
            calls.append('record')

        def stats(self):
            return SimpleNamespace(frames=1)

        def stop_record(self):
            calls.append('stop_record')
            return SimpleNamespace(frames_written=1, frames_dropped=0, last_hresult=0)

        def close(self):
            calls.append('close')

    def fail_pulse(*args):
        raise RuntimeError('pulse failed')

    monkeypatch.setattr(tool, 'GimbalSdk', lambda: sdk)
    monkeypatch.setattr(tinyse_dshow_capture, 'TinySeDShowCapture', Capture)
    monkeypatch.setattr(tool, 'pulse_test', fail_pulse)
    output = tmp_path / 'run'
    with pytest.raises(RuntimeError, match=f'{failure} failed'):
        tool.main(['--output', str(output)])
    assert sdk.commands[-1] == (0, 0)
    assert calls[-1] == 'close'
    assert ('stop_record' in calls) == (failure == 'pulse')
    report = json.loads((output / 'report.json').read_text())
    assert report['status'] == 'incomplete'
    assert report['stop_command_sent'] is True
    assert report['hardware_motion_verified'] is False
