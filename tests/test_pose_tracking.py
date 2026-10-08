from types import SimpleNamespace

import pytest

from camera.pose_tracking import PoseTrackingMailbox
from vision.foot_reference import Landmark


def update(*, index=1, epoch=1, callback=10.0, mapped=10.0, status='pose'):
    pose = SimpleNamespace(landmarks_33=(Landmark(.8, .5, 0, .9, .9),) * 33)
    source = SimpleNamespace(frame_index=index, camera_clock_epoch=epoch,
                             callback_time_s=callback, clock_sync_status='ready')
    record = SimpleNamespace(frame_metadata=source, frame_timestamp_s=mapped,
                             pose=pose, error=None)
    return SimpleNamespace(status=status, inference=record)


def test_shared_pose_drives_speed_without_refreshing_its_age():
    box = PoseTrackingMailbox()
    box.submit(update(callback=10.1))
    command = box.command(10.15)
    assert (command.pitch, command.pan) == pytest.approx((0, 57.6))
    assert command.captured_at == 10.0
    assert box.command(10.251).reason == 'stale_frame'
    assert box.command(10.251).pan == 0


@pytest.mark.parametrize('status', ['loading', 'ready', 'no_pose', 'inference_error',
                                  'clock_reset', 'stopped', 'unavailable:model'])
def test_explicit_invalidation_cancels_motion(status):
    box = PoseTrackingMailbox()
    box.submit(update())
    assert box.command(10.1).pan > 0
    box.submit(update(status=status))
    assert box.command(10.1).pan == 0
    box.submit(update(index=2, epoch=2 if status == 'clock_reset' else 1))
    assert (box.command(10.1).pan == 0) == (status == 'stopped')


def test_frame_epoch_and_order_reject_old_results_and_accept_new_stream():
    box = PoseTrackingMailbox()
    box.submit(update(index=20, epoch=3))
    assert box.command(10.1).pan > 0
    for item in [update(index=19, epoch=3), update(index=99, epoch=2), update(index=20, epoch=3)]:
        box.submit(item)
        assert box.command(10.1).inference.frame_metadata.frame_index == 20
    box.submit(update(index=0, epoch=4))
    assert box.command(10.1).pan > 0


@pytest.mark.parametrize('callback,mapped', [(10.2, 10), (10, 10.102),
                                           (float('nan'), 10), (10, float('inf'))])
def test_future_or_nonfinite_timestamps_never_move(callback, mapped):
    box = PoseTrackingMailbox()
    box.submit(update(callback=callback, mapped=mapped))
    assert box.command(10.1).reason == 'invalid_frame_time'


def test_missing_metadata_errors_and_degraded_sync_stop():
    for kind in ('metadata', 'error', 'sync'):
        box = PoseTrackingMailbox()
        item = update()
        if kind == 'metadata': item.inference.frame_metadata = None
        if kind == 'error': item.inference.error = 'failure'
        if kind == 'sync': item.inference.frame_metadata.clock_sync_status = 'degraded'
        box.submit(item)
        assert box.command(10.1).pan == 0


@pytest.mark.parametrize('status', ['unknown', '', None, 'degraded'])
def test_unknown_sync_cancels_pending_motion(status):
    box = PoseTrackingMailbox()
    box.submit(update())
    pending = box.command(10.1)
    item = update(index=2)
    item.inference.frame_metadata.clock_sync_status = status
    box.submit(item)
    assert not box.is_current(pending)
    assert box.command(10.1).pan == 0


def test_callbacks_keep_only_latest_record_without_invoking_sdk():
    box = PoseTrackingMailbox()
    for index in range(1000):
        box.submit(update(index=index))
    assert box.command(10.1).inference.frame_metadata.frame_index == 999


def test_old_result_cannot_overwrite_a_new_unconsumed_result():
    box = PoseTrackingMailbox()
    box.submit(update(index=20, epoch=3))
    box.submit(update(index=19, epoch=3))
    assert box.command(10.1).inference.frame_metadata.frame_index == 20


def test_reset_barrier_survives_new_pose_and_rejects_previous_epoch():
    box = PoseTrackingMailbox()
    box.submit(update(index=20, epoch=3))
    pending = box.command(10.1)
    box.submit(update(status='clock_reset', epoch=3))
    box.submit(update(index=21, epoch=3))
    assert not box.is_current(pending)
    assert box.command(10.1).pan == 0
    assert box.command(10.1).pan == 0
    box.submit(update(index=0, epoch=4))
    assert box.command(10.1).pan > 0


def test_loss_followed_by_fresh_pose_still_delivers_one_stop():
    box = PoseTrackingMailbox()
    box.submit(update())
    pending = box.command(10.1)
    box.submit(update(status='no_pose'))
    box.submit(update(index=2))
    assert not box.is_current(pending)
    assert box.command(10.1).pan == 0
    assert box.command(10.1).pan > 0
