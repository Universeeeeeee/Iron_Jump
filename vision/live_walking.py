"""Live anatomical leg display and independent checks of walking contacts."""
import logging
from dataclasses import dataclass
from pathlib import Path
import threading
import time

from .foot_reference import FootLabel, VisionConfig, classify_landing_event, unknown_decision
from .framing import FramingCheck, check_framing
from .leg_identity import LegIdentityAnalyzer, LegIdentityResult, LegIdentityState
from .mediapipe_pose import MediaPipePoseAdapter
from .service import EventHook, FootVisionService, PoseFrameMetadata, PoseInferenceRecord
from .time_sync import CameraClockSynchronizer, ClockSyncStatus


class _PreviewAdapter(MediaPipePoseAdapter):
    def infer_bgr(self, frame, timestamp_ms):
        import cv2
        height, width = frame.shape[:2]
        if width > 640:
            frame = cv2.resize(frame, (640, round(height * 640 / width)), interpolation=cv2.INTER_AREA)
        return super().infer_bgr(frame, timestamp_ms)


@dataclass(frozen=True)
class LivePoseUpdate:
    """Public, non-Qt output; consumers must enqueue quickly, never call SDK here."""

    status: str
    inference: PoseInferenceRecord | None = None
    identity: LegIdentityResult | None = None
    framing: FramingCheck | None = None


def classify_walking_contact(event_id, timestamp, samples, config):
    if any(sample.identity_reject_reason != "" for sample in samples):
        return unknown_decision(event_id, timestamp, "identity_ambiguous")
    ordered = sorted(samples, key=lambda sample: sample.timestamp_s)
    # The live walking cadence is 50 ms. Allow one missed inference, but do not
    # infer a landing across a longer interval with no visual observation.
    if any(b.timestamp_s - a.timestamp_s > .100 + 1e-9
           for a, b in zip(ordered, ordered[1:])):
        return unknown_decision(event_id, timestamp, "pose_gap_exceeded")
    decision = classify_landing_event(event_id, timestamp, samples, config)
    if decision.label is FootLabel.BOTH:
        return unknown_decision(event_id, timestamp, "both_feet_ambiguous")
    return decision


class LiveWalkingVision:
    """No Qt access on camera/inference threads; UI polls bounded state."""

    def __init__(self, model_path=None, *, service_factory=FootVisionService, clock=time.perf_counter):
        self._clock = clock
        self._lock = threading.RLock()
        self._updates_lock = threading.RLock()
        self.pose_updates = EventHook()
        self._camera_clock = CameraClockSynchronizer()
        self._camera_clock_epoch = 0
        self._grid_clock = CameraClockSynchronizer(min_samples=8, min_span_s=.5)
        self._identity = LegIdentityAnalyzer()
        self._pose = None
        self._pose_status = "正在加载人体识别…"
        self._service_status = "loading"
        self._last_frame_time = -1.0
        self._last_grid_frame = None
        self._stream = None
        self._seen_contacts = set()
        self._events = {}
        self._event_serial = 0
        self._latest_check = None
        self._verification_after = float('-inf')
        self._stopped = False
        config = VisionConfig(pre_event_ms=150, post_event_ms=150,
                              inference_interval_ms=50, decision_timeout_ms=450,
                              max_frames=20, frame_buffer_ms=1000)
        model_path = model_path or Path(__file__).resolve().parents[1] / 'models/pose_landmarker_full.task'
        self._service = service_factory(config, model_path, adapter_factory=_PreviewAdapter,
                                        classifier=classify_walking_contact, latest_frame_only=True)
        self._service.pose_inference_ready.connect(self._on_inference)
        self._service.status_changed.connect(self._on_status)
        self._service.decision_ready.connect(self._on_decision)

    def start(self):
        self._publish(LivePoseUpdate('loading'))
        self._service.start()

    def stop(self):
        with self._lock:
            first_stop = not self._stopped
            self._stopped = True
            self._pose = None
            self._events.clear()
        if first_stop:
            self._publish(LivePoseUpdate('stopped'))
        self._service.stop()

    def _publish(self, update):
        # Serialize invalidation with worker results so a stopped stream cannot
        # publish a new target after its terminal notification.
        with self._updates_lock:
            with self._lock:
                if self._stopped and update.status != 'stopped':
                    return
                source = update.inference.frame_metadata if update.inference else None
                if update.inference is not None and (
                    self._camera_clock.snapshot.status is ClockSyncStatus.DEGRADED
                    or source is not None and source.camera_clock_epoch != self._camera_clock_epoch
                ):
                    update = LivePoseUpdate('clock_reset', update.inference)
            self.pose_updates.emit(update)

    def submit_camera_frame(self, frame, timing):
        with self._lock:
            if self._stopped:
                return
            epoch = self._camera_clock_epoch
            self._recover_clock(self._camera_clock, timing.callback_time_s)
            sync = self._camera_clock.observe(timing.sample_time_s, timing.callback_time_s,
                                               frame_index=timing.frame_index)
            timestamp = sync.aligned_time_s if sync.status is ClockSyncStatus.READY else timing.callback_time_s
            dropped = timestamp <= self._last_frame_time
            if not dropped:
                self._last_frame_time = timestamp
            source = PoseFrameMetadata(timing.frame_index, timing.sample_time_s,
                                       timing.callback_time_s, getattr(timing, 'decoded_at_s', None),
                                       sync.status.value, sync.uncertainty_ms,
                                       self._camera_clock_epoch)
        if epoch != source.camera_clock_epoch or sync.status is ClockSyncStatus.DEGRADED:
            self._publish(LivePoseUpdate('clock_reset'))
        if not dropped:
            self._service.submit_frame(frame, timestamp, metadata=source)

    def _recover_clock(self, clock, now):
        if clock.snapshot.status is not ClockSyncStatus.DEGRADED:
            return
        # Start a fresh calibration window; retain the same uncertainty limits.
        # Old in-flight decisions and cached poses must not cross clock epochs.
        clock.reset()
        if clock is self._camera_clock:
            self._camera_clock_epoch += 1
        self._verification_after = max(self._verification_after, now + 1.0)
        for meta in self._events.values():
            meta.update(label='unknown', reason='clock_sync_unavailable')
        self._events.clear()

    def _on_status(self, status):
        with self._lock:
            if self._stopped:
                return
            self._service_status = status
            if status == 'ready':
                # Model loading can temporarily stall native callbacks. Establish
                # clock mappings after loading, not during that startup burst.
                self._camera_clock.reset()
                self._camera_clock_epoch += 1
                self._grid_clock.reset()
                self._last_grid_frame = None
                for meta in self._events.values():
                    meta.update(label='unknown', reason='clock_sync_unavailable')
                self._events.clear()
            elif status.startswith(('unavailable', 'inference_error')):
                logging.getLogger(__name__).warning('Walking vision: %s', status)
                self._pose = None
                self._pose_status = '人体识别不可用，请检查模型与运行环境'
        self._publish(LivePoseUpdate(status))

    def _on_inference(self, record):
        with self._lock:
            if self._stopped:
                return
            source = record.frame_metadata
            if (self._camera_clock.snapshot.status is ClockSyncStatus.DEGRADED
                    or source is not None and source.camera_clock_epoch != self._camera_clock_epoch):
                self._pose = None
                self._pose_status = '正在更新人体识别，请保持下肢完整可见'
                update = LivePoseUpdate('clock_reset', record)
            else:
                update = self._update_pose(record)
        self._publish(update)

    def _update_pose(self, record):
        """Called under the state lock; the public callback runs after release."""
        identity = self._identity.update(record.pose)
        self._pose = record.pose
        if record.pose is None:
            self._pose_status = '请让髋部、双膝和双脚完整进入画面'
        elif identity.state is LegIdentityState.STABLE:
            self._pose_status = '左腿蓝色 · 右腿橙色'
        elif identity.state is LegIdentityState.AMBIGUOUS:
            self._pose_status = '双腿身份暂不确定，请避免交叉或遮挡'
        else:
            self._pose_status = '正在确认左右腿，请保持下肢完整可见'
        status = 'inference_error' if record.error else 'pose' if record.pose is not None else 'no_pose'
        return LivePoseUpdate(status, record, identity, check_framing(record.pose, now_s=self._clock()))

    def submit_walking_snapshot(self, snapshot):
        timing = snapshot.get('device_timing')
        walking = snapshot.get('walking')
        if not timing or walking is None:
            return
        with self._lock:
            if self._stopped:
                return
            if timing['stream_id'] != self._stream:
                self._stream = timing['stream_id']
                self._grid_clock.reset()
                self._last_grid_frame = None
                self._seen_contacts.clear()
                self._events.clear()
                self._latest_check = None
            if timing['frame_index'] != self._last_grid_frame:
                self._recover_clock(self._grid_clock, timing['received_time_s'])
                self._grid_clock.observe(timing['sample_time_s'], timing['received_time_s'],
                                         frame_index=timing['frame_index'])
                self._last_grid_frame = timing['frame_index']
            grid = self._grid_clock.snapshot
            camera = self._camera_clock.snapshot
            for contact in walking.get('contacts', []):
                contact_id = contact['id']
                exclusion = contact.get('exclusion')
                # A confirmed touch is usable before lift-off. The report marks
                # this ordinary ongoing stance incomplete for full-step metrics.
                unavailable = exclusion not in (None, '', 'incomplete_contact', 'pending_touch_order')
                # A confirmed touch can be excluded later (for example after a
                # footprint merge). Revoke both pending and displayed checks.
                for meta in [*self._events.values(), self._latest_check]:
                    if meta is not None and meta['contact_id'] == contact_id:
                        meta['device_side'] = contact['side']
                        if unavailable:
                            meta.update(label='unknown', reason='contact_unavailable', confidence=0.0)
                            self._events.pop(meta['event_id'], None)
                if contact_id in self._seen_contacts or not contact['confirmed']:
                    continue
                if exclusion == 'pending_touch_order':
                    continue
                self._seen_contacts.add(contact_id)
                self._event_serial += 1
                meta = {'event_id': self._event_serial, 'contact_id': contact_id,
                        'device_side': contact['side'], 'label': 'unknown', 'reason': 'pending'}
                self._latest_check = meta
                if unavailable or timing['origin_sample_time_s'] is None:
                    meta['reason'] = 'contact_unavailable'
                elif grid.status is not ClockSyncStatus.READY or camera.status is not ClockSyncStatus.READY:
                    meta['reason'] = 'clock_sync_unavailable'
                else:
                    event_time = timing['origin_sample_time_s'] + contact['start'] + grid.offset_ms / 1000
                    if event_time - .15 < self._verification_after:
                        meta['reason'] = 'clock_sync_unavailable'
                        continue
                    self._events[self._event_serial] = meta
                    self._service.submit_touch_event(self._event_serial, event_time)

    def _on_decision(self, decision):
        with self._lock:
            meta = self._events.pop(decision.event_id, None)
            if self._stopped or meta is None:
                return
            if (self._camera_clock.snapshot.status is not ClockSyncStatus.READY
                    or self._grid_clock.snapshot.status is not ClockSyncStatus.READY):
                meta['reason'] = 'clock_sync_unavailable'
                return
            meta.update(label=decision.label.value, reason=decision.reason, confidence=decision.confidence)

    def display_state(self):
        with self._lock:
            pose, status = self._pose, self._pose_status
            now = self._clock()
            framing = check_framing(pose, now_s=now)
            if pose is not None and not 0 <= now - pose.timestamp_s <= .25:
                pose = None
                status = '正在更新人体识别，请保持下肢完整可见'
            if self._service_status == 'ready' or pose is not None:
                status = framing.message + (' · ' + status if framing.ready else '')
            check = dict(self._latest_check) if self._latest_check is not None else None
        return pose, status, check


def walking_check_text(check):
    if check is None:
        return ''
    prefix = f"第 {check['contact_id'] + 1} 次触地："
    side = {'left': '左脚', 'right': '右脚'}.get(check['label'])
    if side is None:
        if check['reason'] == 'pending':
            return prefix + '正在核验'
        if check['reason'] == 'clock_sync_unavailable':
            return prefix + '画面与设备尚未同步，暂无法核验'
        return prefix + '暂无法核验左右脚'
    text = prefix + '视觉' + side
    if check['device_side'] in {'left', 'right'}:
        text += ' · 与光栅推断一致' if check['device_side'] == check['label'] else ' · 与光栅推断不一致，请核对'
    return text
