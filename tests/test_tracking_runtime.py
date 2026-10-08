import pytest

from camera.tracking_runtime import TrackingRuntime
from tests.test_pose_tracking import update


class Sdk:
    def __init__(self):
        self.commands = []

    def set_speed(self, pitch, pan):
        self.commands.append((pitch, pan))

    def disable_ai(self):
        self.commands.append('ai_off_widest')


def runtime():
    sdk, logs = Sdk(), []
    return TrackingRuntime(sdk, logs.append, clock=lambda: 10.1), sdk, logs


def test_mode_initialization_and_stop_precede_any_motion():
    worker, sdk, logs = runtime()
    worker.start(1)
    assert sdk.commands == [(0, 0), 'ai_off_widest']
    worker.submit(1, update())
    worker.tick()
    assert sdk.commands[-1][1] > 0
    worker.stop()
    worker.submit(1, update(index=2))
    worker.tick()
    assert sdk.commands[-1] == (0, 0)
    assert all('started_at' in row and 'returned_at' in row
               for row in logs if row['event'] == 'sdk_call')


def test_previous_session_cannot_resume_after_switching_modes():
    worker, sdk, _ = runtime()
    worker.start(1)
    worker.stop()
    worker.start(2)
    worker.submit(1, update())
    worker.tick()
    assert sdk.commands[-1] == (0, 0)
    worker.submit(2, update())
    worker.tick()
    assert sdk.commands[-1][1] > 0
    with pytest.raises(ValueError): worker.start(2)


@pytest.mark.parametrize('method', ['set_ai_mode', 'set_ai_off', 'set_fov'])
def test_builtin_ai_and_crop_cannot_compete_with_speed_mode(method):
    worker, sdk, _ = runtime()
    worker.start(1)
    calls = []
    with pytest.raises(RuntimeError):
        worker.setting(method, lambda: calls.append(method))
    assert not calls


def test_slow_setting_clears_old_motion_before_entering_native_call():
    worker, sdk, _ = runtime()
    worker.start(1)
    worker.submit(1, update())
    worker.tick()
    def setting():
        assert sdk.commands[-1] == (0, 0)
        return 0
    assert worker.setting('set_auto_focus', setting) == 0
    worker.tick()
    assert sdk.commands[-1] == (0, 0)


def test_initialization_failure_and_native_motion_error_do_not_resume():
    worker, sdk, logs = runtime()
    def fail(): raise RuntimeError('FOV failed')
    sdk.disable_ai = fail
    with pytest.raises(RuntimeError): worker.start(1)
    assert not worker.active
    assert logs[-1]['error'] == 'FOV failed'
    sdk.disable_ai = lambda: None
    worker.start(2)
    original = sdk.set_speed
    def motion(pitch, pan):
        if pan: raise RuntimeError('SDK rejected speed')
        original(pitch, pan)
    sdk.set_speed = motion
    worker.submit(2, update())
    with pytest.raises(RuntimeError): worker.tick()
    assert not worker.active
    assert sdk.commands[-1] == (0, 0)


def test_invalidation_during_native_call_stops_immediately_on_return():
    worker, sdk, _ = runtime()
    worker.start(1)
    original = sdk.set_speed
    def speed(pitch, pan):
        original(pitch, pan)
        if pan:
            worker.submit(1, update(status='no_pose'))
    sdk.set_speed = speed
    worker.submit(1, update())
    worker.tick()
    assert sdk.commands[-2][1] > 0
    assert sdk.commands[-1] == (0, 0)


def test_inflight_pose_from_before_a_slow_setting_cannot_resume_motion():
    worker, sdk, _ = runtime()
    worker.start(1)
    worker.submit(1, update())
    worker.tick()
    worker.setting('set_auto_focus', lambda: 0)
    worker.submit(1, update(index=2))
    worker.tick()
    assert sdk.commands[-1] == (0, 0)
    worker.submit(1, update(index=3, callback=10.1, mapped=10.1))
    worker.tick()
    assert sdk.commands[-1][1] > 0


def test_pose_arriving_during_a_slow_setting_is_also_revoked():
    worker, sdk, _ = runtime()
    worker.start(1)
    worker.setting('set_auto_focus', lambda: (worker.submit(1, update(index=2)), 0)[1])
    worker.tick()
    assert sdk.commands[-1] == (0, 0)
