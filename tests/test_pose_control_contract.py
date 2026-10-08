"""Cross-branch JSON contract checks; SDK/model/camera are never opened.

Set IRON_JUMP_CONTROL_ROOT to the control worktree until integration is merged.
"""
from dataclasses import asdict, replace
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from tests.test_leg_identity import _sample
from tests.test_live_walking_vision import Service
from vision.foot_reference import FootPoseSample, Landmark
from vision.live_walking import LivePoseUpdate, LiveWalkingVision
from vision.service import PoseFrameMetadata, PoseInferenceRecord


@pytest.fixture
def control(monkeypatch):
    specified = os.environ.get('IRON_JUMP_CONTROL_ROOT')
    root = Path(specified) if specified else Path(__file__).resolve().parents[1]
    if not specified and not (root / 'camera/pose_transport.py').exists():
        pytest.skip('Control integration is not yet in this worktree')
    # Load only the four pure modules, restoring sys.modules after each test.
    # Never fall back silently to a cached module from a different worktree.
    for name in ('vision.gimbal_tracking', 'camera.pose_tracking',
                 'camera.pose_transport', 'camera.tracking_runtime'):
        spec = importlib.util.spec_from_file_location(name, root / (name.replace('.', '/') + '.py'))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    transport = sys.modules['camera.pose_transport']
    runtime_module = sys.modules['camera.tracking_runtime']
    now, commands, logs = [10.1], [], []

    class Sdk:
        def disable_ai(self): pass
        def set_speed(self, pitch, pan): commands.append((pitch, pan))

    runtime = runtime_module.TrackingRuntime(Sdk(), logs.append, clock=lambda: now[0])
    runtime.start(1)
    return transport.PoseRelay(), runtime, transport.decode_update, now, commands, logs


def update(index=1, epoch=1, status='pose', timestamp=10.0):
    pose = replace(_sample(timestamp),
                   landmarks_33=(Landmark(.8, .5, 0, .9, .9),) * 33)
    source = PoseFrameMetadata(index, .04, timestamp, timestamp + .02,
                               'ready', 1.25, epoch)
    record = PoseInferenceRecord(timestamp, timestamp + .02, timestamp + .04,
                                 pose, frame_metadata=source)
    return LivePoseUpdate(status, record)


def packet(relay, generation=1):
    return json.loads(json.dumps(relay.packet(generation)))


def restore_pose(raw):
    if raw is None:
        return None
    values = {name: Landmark(**value) if isinstance(value, dict) else value
              for name, value in raw.items()}
    if raw.get('landmarks_33') is not None:
        values['landmarks_33'] = tuple(Landmark(**point) for point in raw['landmarks_33'])
    return FootPoseSample(**values)


def test_real_public_update_survives_json_with_all_fields(control):
    relay, _, decode, _, _, _ = control
    live = LiveWalkingVision(service_factory=Service, clock=lambda: 10.1)
    updates = []
    live.pose_updates.connect(updates.append)
    live.pose_updates.connect(relay.submit)
    record = update(epoch=0).inference
    live._service.pose_inference_ready.emit(record)
    encoded = packet(relay)['update']
    decoded = decode(encoded)
    assert decoded.inference.frame_metadata.callback_time_s == 10.0
    assert decoded.inference.frame_metadata.clock_sync_uncertainty_ms == 1.25
    assert len(decoded.inference.pose.landmarks_33) == 33
    assert decoded.identity.reason == encoded['identity']['reason']
    assert decoded.framing.ready == encoded['framing']['ready']
    assert encoded == json.loads(json.dumps(asdict(updates[-1])))


def test_none_then_pose_preserves_stop_through_json_coalescing(control):
    relay, runtime, _, _, commands, _ = control
    live = LiveWalkingVision(service_factory=Service, clock=lambda: 10.1)
    live.pose_updates.connect(relay.submit)
    live._service.pose_inference_ready.emit(update(epoch=0).inference)
    runtime.submit_packet(packet(relay)); runtime.tick()
    assert commands[-1][1] > 0
    live._service.pose_inference_ready.emit(replace(update(2, epoch=0).inference, pose=None))
    live._service.pose_inference_ready.emit(update(3, epoch=0).inference)
    runtime.submit_packet(packet(relay)); runtime.tick()
    assert commands[-1] == (0, 0)
    runtime.tick()
    assert commands[-1][1] > 0


@pytest.mark.parametrize('with_source', [False, True])
def test_late_reset_does_not_permanently_reject_current_epoch(control, with_source):
    relay, runtime, _, _, commands, _ = control
    relay.submit(update(20, epoch=4))
    runtime.submit_packet(packet(relay)); runtime.tick()
    relay.submit(update(99, epoch=2, status='clock_reset') if with_source
                 else LivePoseUpdate('clock_reset'))
    relay.submit(update(21, epoch=4))
    runtime.submit_packet(packet(relay)); runtime.tick()
    assert commands[-1] == (0, 0)
    runtime.tick()
    assert commands[-1][1] > 0


@pytest.mark.parametrize('status', ['no_pose', 'inference_error', 'unavailable: model', 'stopped'])
def test_invalidation_cancels_old_pending_command_and_terminal_stop(control, status):
    relay, runtime, _, _, commands, _ = control
    relay.submit(update())
    runtime.submit_packet(packet(relay))
    old_command = runtime.mailbox.command(10.1)
    assert old_command.pan > 0
    relay.submit(LivePoseUpdate(status))
    relay.submit(update(2))
    runtime.submit_packet(packet(relay))
    assert not runtime.mailbox.is_current(old_command)
    runtime.tick()
    assert commands[-1] == (0, 0)
    runtime.tick()
    assert (commands[-1][1] > 0) == (status != 'stopped')


def test_json_delay_does_not_refresh_frame_or_accept_previous_mode(control):
    relay, runtime, _, now, commands, _ = control
    relay.submit(update())
    delayed = packet(relay)
    now[0] = 10.251
    runtime.submit_packet(delayed); runtime.tick()
    assert commands[-1] == (0, 0)
    runtime.stop(); runtime.start(2)
    runtime.submit_packet(delayed); runtime.tick()
    assert commands[-1] == (0, 0)


def test_slow_setting_requires_a_frame_from_after_its_return(control):
    relay, runtime, _, now, commands, _ = control
    relay.submit(update())
    old = packet(relay)
    runtime.submit_packet(old); runtime.tick()
    assert commands[-1][1] > 0
    runtime.setting('set_auto_focus', lambda: 0)
    runtime.submit_packet(old); runtime.tick()
    assert commands[-1] == (0, 0)
    now[0] = 10.15
    relay.submit(update(2, timestamp=10.12))
    runtime.submit_packet(packet(relay)); runtime.tick()
    assert commands[-1][1] > 0


@pytest.mark.parametrize('run', ['side_audit2', 'side_audit5_wide'])
def test_saved_pose_outputs_keep_target_and_quality_through_json(control, run):
    tracking = sys.modules['vision.gimbal_tracking']
    full_body_target = tracking.full_body_target
    relay, runtime, decode, now, commands, _ = control
    root = Path(__file__).resolve().parents[1]
    path = root / 'exports/tracking_diagnosis_20261008' / run / 'audit.json'
    if not path.exists():
        pytest.skip('Saved field evidence is not present in this checkout')
    data = json.loads(path.read_text())
    live = LiveWalkingVision(service_factory=Service, clock=lambda: now[0])
    live.pose_updates.connect(relay.submit)
    for index, item in enumerate(data['inferences']):
        saved = item['record']
        now[0] = saved['inference_end_timestamp_s']
        # Historical logs lack raw callback metadata. Use a declared synthetic
        # callback here to check serialization only, never to measure latency.
        source = PoseFrameMetadata(index, index * .05, saved['frame_timestamp_s'],
                                   None, 'ready', None, 0)
        record = PoseInferenceRecord(saved['frame_timestamp_s'],
                                     saved['inference_start_timestamp_s'], now[0],
                                     restore_pose(saved['pose']), saved.get('error'), source)
        live._service.pose_inference_ready.emit(record)
        payload = packet(relay)
        decoded = decode(payload['update'])
        target = full_body_target(record.pose)
        assert full_body_target(decoded.inference.pose) == target
        runtime.submit_packet(payload)
        runtime.tick(); runtime.tick()  # Consume any loss barrier, then candidate.
        expected = (tracking.framing_velocity(tracking.body_framing(record.pose))
                    if hasattr(tracking, 'framing_velocity')
                    else tracking.tracking_velocity(target))
        assert commands[-1] == pytest.approx(expected)


def test_edge_correction_changes_only_speed_policy_after_json(control):
    tracking = sys.modules['vision.gimbal_tracking']
    if not hasattr(tracking, 'framing_velocity'):
        pytest.skip('This frozen snapshot still uses the earlier center-only policy')
    relay, runtime, _, _, commands, _ = control
    original = update()
    points = [Landmark(.5, .5, 0, .9, .9)] * 33
    points[0] = replace(points[0], y=.1)
    points[31] = replace(points[31], y=1.)
    pose = replace(original.inference.pose, landmarks_33=tuple(points))
    current = replace(original, inference=replace(original.inference, pose=pose))
    assert tracking.full_body_target(pose) == pytest.approx((.5, .55))
    assert tracking.tracking_velocity((.5, .55)) == (0., 0.)
    relay.submit(current)
    payload = packet(relay)
    assert payload['update']['inference']['pose'] == json.loads(json.dumps(asdict(pose)))
    runtime.submit_packet(payload); runtime.tick()
    assert commands[-1] == pytest.approx((4., 0.))
