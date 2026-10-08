"""Bounded handoff from the shared pose worker to the SDK owner."""
from dataclasses import dataclass
import math
import threading

from vision.gimbal_tracking import body_framing, framing_velocity


@dataclass(frozen=True)
class PoseSpeedCommand:
    pitch: float = 0.0
    pan: float = 0.0
    captured_at: float = 0.0
    reason: str = 'no_pose'
    inference: object = None
    motion_generation: int = 0
    framing: object = None


class PoseTrackingMailbox:
    """submit() never calls SDK or Qt; command() runs on the control side."""

    def __init__(self, timeout=.25):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._latest = None
        self._stopped = False
        self._last_key = None
        self._minimum_epoch = 0
        self._motion_generation = 0
        self._zero_barrier = None

    def submit(self, update):
        with self._lock:
            if self._stopped:
                return
            record = update.inference
            source = record.frame_metadata if record else None
            reason = update.status
            if reason == 'pose' and (source is None or record.error
                                    or source.clock_sync_status not in {'ready', 'warming_up'}):
                reason = 'invalid_inference'
            if reason != 'pose':
                self._motion_generation += 1
                self._zero_barrier = reason
                self._latest = None
                self._stopped = update.status == 'stopped'
                if update.status == 'clock_reset' and source is not None:
                    epoch = source.camera_clock_epoch
                    self._minimum_epoch = max(self._minimum_epoch, epoch + 1)
                return
            if source is not None:
                key = source.camera_clock_epoch, source.frame_index
                if (key[0] < self._minimum_epoch
                        or self._last_key is not None and key <= self._last_key):
                    return
                # Maintain provenance at publication, including unconsumed frames.
                self._last_key = key
            self._latest = update

    def is_current(self, command):
        with self._lock:
            return command.motion_generation == self._motion_generation and not self._stopped

    def command(self, now):
        with self._lock:
            generation = self._motion_generation
            def stopped(reason, record=None):
                return PoseSpeedCommand(reason=reason, inference=record,
                                        motion_generation=generation)
            if self._zero_barrier is not None:
                reason, self._zero_barrier = self._zero_barrier, None
                return stopped(reason)
            update = self._latest
            if update is None or update.status != 'pose':
                return stopped(update.status if update else 'no_pose')
            record = update.inference
            source = record.frame_metadata if record else None
            if source is None:
                return stopped('missing_frame_metadata', record)
            callback = source.callback_time_s
            mapped = record.frame_timestamp_s
            # VIDEO inference rounds to milliseconds. Only its mapped time gets
            # a 1 ms allowance; a future host callback is always invalid.
            if (not all(math.isfinite(v) for v in (now, callback, mapped))
                    or callback > now or mapped > now + .001):
                return stopped('invalid_frame_time', record)
            stamp = min(callback, mapped)
            if now - stamp > self.timeout:
                return stopped('stale_frame', record)
            if record.error or source.clock_sync_status not in {'ready', 'warming_up'}:
                return stopped('invalid_inference', record)
            framing = body_framing(record.pose)
            if framing is None:
                return stopped('invalid_target', record)
            pitch, pan = framing_velocity(framing)
            return PoseSpeedCommand(pitch, pan, stamp, 'tracking', record, generation, framing)
