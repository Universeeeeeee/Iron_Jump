"""Image-error controller for the standalone Tiny SE experiment."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TrackingSpeeds:
    pan_gain: float = 240.0
    pitch_gain: float = 80.0
    pan_max: float = 90.0
    pitch_max: float = 30.0
    pan_sign: int = 1
    pitch_sign: int = 1
    deadzone: float = 0.06

    def __post_init__(self):
        for name in ('pan_gain', 'pitch_gain', 'pan_max', 'pitch_max'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if self.pan_max > 180 or self.pitch_max > 90:
            raise ValueError('SDK limits: pan <= 180, pitch <= 90')
        if self.pan_sign not in (-1, 1) or self.pitch_sign not in (-1, 1):
            raise ValueError('axis signs must be -1 or 1')
        if not math.isfinite(self.deadzone) or not 0 <= self.deadzone < .5:
            raise ValueError('deadzone must be in [0, .5)')


def full_body_target(pose):
    if pose is None or pose.landmarks_33 is None or len(pose.landmarks_33) != 33:
        return None
    def visible(p):
        return (all(math.isfinite(v) for v in (p.x, p.y, p.quality))
                and p.quality >= .65 and 0 <= p.x <= 1 and 0 <= p.y <= 1)

    points = pose.landmarks_33
    if any(not visible(points[i]) for i in (11, 12, 23, 24, 27, 28)):
        return None
    # Include visible head, hands and feet; an occluded hand need not stop tracking.
    points = tuple(p for p in points if visible(p))
    return ((min(p.x for p in points) + max(p.x for p in points)) / 2,
            (min(p.y for p in points) + max(p.y for p in points)) / 2)


def tracking_velocity(target, settings=TrackingSpeeds()):
    """Return (pitch, pan); x/y are normalized unmirrored image coordinates."""
    if target is None:
        return 0.0, 0.0
    if len(target) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in target):
        return 0.0, 0.0

    def axis(error, gain, limit, sign):
        error = math.copysign(max(0, abs(error) - settings.deadzone), error)
        return sign * max(-limit, min(limit, error * gain))

    x, y = target
    return (axis(y - .5, settings.pitch_gain, settings.pitch_max, settings.pitch_sign),
            axis(x - .5, settings.pan_gain, settings.pan_max, settings.pan_sign))
