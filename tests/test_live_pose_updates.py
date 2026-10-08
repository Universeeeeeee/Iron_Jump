"""Public pose output preserves frame provenance and explicit invalidation."""
from dataclasses import replace
import threading

import pytest

from tests.test_leg_identity import _sample
from tests.test_live_walking_vision import Service
from vision.foot_reference import VisionConfig
from vision.live_walking import LiveWalkingVision
from vision.service import FootVisionService, PoseFrameMetadata, PoseInferenceRecord


def metadata(index=1, epoch=0):
    return PoseFrameMetadata(index, .04, 100.04, 100.05, 'warming_up', None, epoch)


@pytest.mark.parametrize('outcome', ['pose', 'none', 'error'])
def test_service_keeps_metadata_of_the_inferred_input(outcome):
    ready = threading.Event()
    records = []
    pixels = object()
    source = metadata()

    class Adapter:
        def __init__(self, path): pass
        def open(self): pass
        def close(self): pass
        def infer_bgr(self, frame, timestamp):
            assert frame is pixels
            if outcome == 'error': raise RuntimeError('inference failed')
            return _sample(timestamp / 1000) if outcome == 'pose' else None

    service = FootVisionService(VisionConfig(), 'unused', adapter_factory=Adapter,
                                clock=lambda: 100.06)
    service.pose_inference_ready.connect(lambda record: (records.append(record), ready.set()))
    service.start()
    try:
        service.submit_frame(pixels, 100.0396, metadata=source)
        assert ready.wait(1)
        assert records[0].frame_metadata is source
        assert records[0].frame_timestamp_s == pytest.approx(100.040)
        assert records[0].frame_metadata.callback_time_s == 100.04
        assert (records[0].error is not None) == (outcome == 'error')
    finally:
        service.stop()


def test_latest_only_drop_does_not_attach_a_different_frames_metadata():
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    records = []

    class Adapter:
        def __init__(self, path): pass
        def open(self): entered.set(); release.wait(1)
        def close(self): pass
        def infer_bgr(self, frame, timestamp):
            assert frame == 'new'
            return None

    service = FootVisionService(VisionConfig(), 'unused', adapter_factory=Adapter,
                                clock=lambda: 100.2, latest_frame_only=True)
    service.pose_inference_ready.connect(lambda record: (records.append(record), done.set()))
    service.start()
    try:
        assert entered.wait(1)
        service.submit_frame('old', 100.0, metadata=metadata(1))
        service.submit_frame('new', 100.1, metadata=metadata(2))
        release.set()
        assert done.wait(1)
        assert records[0].frame_metadata.frame_index == 2
    finally:
        release.set()
        service.stop()


def test_public_updates_expose_pose_identity_framing_and_missing_person():
    live = LiveWalkingVision(service_factory=Service, clock=lambda: 1.1)
    updates = []
    live.pose_updates.connect(updates.append)
    pose = _sample(1.1)
    record = PoseInferenceRecord(1.1, 1.1, 1.1, pose)
    live._service.pose_inference_ready.emit(record)
    assert updates[-1].status == 'pose'
    assert updates[-1].inference is record
    assert updates[-1].identity is not None
    assert updates[-1].framing.ready
    live._service.pose_inference_ready.emit(replace(record, pose=None))
    assert updates[-1].status == 'no_pose'
    assert not updates[-1].framing.ready
    live._service.pose_inference_ready.emit(replace(record, pose=None, error='failed'))
    assert updates[-1].status == 'inference_error'
    assert updates[-1].inference.error == 'failed'


def test_stop_notifies_before_waiting_and_late_results_are_ignored():
    live = LiveWalkingVision(service_factory=Service, clock=lambda: 1.1)
    updates = []
    live.pose_updates.connect(updates.append)
    def stop():
        assert updates[-1].status == 'stopped'
    live._service.stop = stop
    live.stop()
    live._service.pose_inference_ready.emit(PoseInferenceRecord(1.1, 1.1, 1.1, _sample(1.1)))
    assert [u.status for u in updates] == ['stopped']


def test_old_clock_epoch_is_not_published_as_a_current_target():
    live = LiveWalkingVision(service_factory=Service, clock=lambda: 100.1)
    updates = []
    live.pose_updates.connect(updates.append)
    live._service.status_changed.emit('ready')
    live._service.pose_inference_ready.emit(PoseInferenceRecord(
        100.04, 100.06, 100.07, _sample(100.04), frame_metadata=metadata(epoch=0)))
    assert updates[-1].status == 'clock_reset'
    assert updates[-1].identity is None
    assert live.display_state()[0] is None


def test_live_submission_passes_original_callback_not_completion_time():
    from types import SimpleNamespace
    live = LiveWalkingVision(service_factory=Service, clock=lambda: 500)
    timing = SimpleNamespace(frame_index=7, sample_time_s=.1,
                             callback_time_s=100.1, decoded_at_s=100.2)
    live.submit_camera_frame(object(), timing)
    source = live._service.metadata[-1]
    assert source.frame_index == 7
    assert source.sample_time_s == .1
    assert source.callback_time_s == 100.1
    assert source.decoded_at_s == 100.2
    assert source.clock_sync_status == 'warming_up'


def test_clock_degradation_invalidates_even_a_dropped_frame_and_inflight_pose():
    from types import SimpleNamespace
    live = LiveWalkingVision(service_factory=Service, clock=lambda: 100.1)
    updates = []
    live.pose_updates.connect(updates.append)
    timing = SimpleNamespace(frame_index=1, sample_time_s=.04, callback_time_s=100.04)
    live.submit_camera_frame(object(), timing)
    source = live._service.metadata[-1]
    # Repeated frame/sample time degrades synchronization; timestamp filtering
    # also drops this input, but control still needs an immediate invalidation.
    live.submit_camera_frame(object(), timing)
    assert len(live._service.frames) == 1
    assert updates[-1].status == 'clock_reset'
    live._service.pose_inference_ready.emit(PoseInferenceRecord(
        100.04, 100.05, 100.06, _sample(100.04), frame_metadata=source))
    assert updates[-1].status == 'clock_reset'
    assert updates[-1].identity is None
    assert live.display_state()[0] is None


def test_concurrent_stop_is_terminal_after_an_inflight_callback():
    live = LiveWalkingVision(service_factory=Service, clock=lambda: 1.1)
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    updates = []

    def receive(update):
        updates.append(update.status)
        if update.status == 'pose':
            entered.set()
            assert release.wait(1)

    live.pose_updates.connect(receive)
    record = PoseInferenceRecord(1.1, 1.1, 1.1, _sample(1.1))
    worker = threading.Thread(target=live._service.pose_inference_ready.emit, args=(record,))
    def stop():
        live.stop()
        stopped.set()
    stopper = threading.Thread(target=stop)
    worker.start()
    try:
        assert entered.wait(1)
        stopper.start()
    finally:
        release.set()
        worker.join(1)
        stopper.join(1)
    assert stopped.is_set()
    live._service.pose_inference_ready.emit(record)
    assert updates == ['pose', 'stopped']


def test_metadata_wrapping_preserves_event_classification():
    from tests.test_vision_service import _FakeAdapter
    from vision.foot_reference import FootLabel
    done = threading.Event()
    decisions, records = [], []
    config = VisionConfig(pre_event_ms=100, post_event_ms=60,
                          inference_interval_ms=20, decision_timeout_ms=200)
    service = FootVisionService(config, 'unused', adapter_factory=_FakeAdapter,
                                clock=lambda: .300)
    service.pose_inference_ready.connect(records.append)
    service.decision_ready.connect(lambda decision: (decisions.append(decision), done.set()))
    service.start()
    try:
        for index in range(16):
            service.submit_frame(object(), index * .02, metadata=metadata(index))
        service.submit_touch_event(9, .150)
        assert done.wait(1)
        assert decisions[0].label is FootLabel.LEFT
        assert decisions[0].event_id == 9
        assert records
        assert all(record.frame_timestamp_s == pytest.approx(
            record.frame_metadata.frame_index * .02) for record in records)
    finally:
        service.stop()
