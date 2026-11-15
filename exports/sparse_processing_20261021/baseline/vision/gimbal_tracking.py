"""Image-error controller for the standalone Tiny SE experiment."""
from dataclasses import dataclass, replace
import math


@dataclass(frozen=True)
class TrackingSpeeds:
    pan_gain: float = 300.0
    pitch_gain: float = 80.0
    pan_max: float = 120.0
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


def _visible(p):
    return (all(math.isfinite(v) for v in (p.x, p.y, p.visibility, p.presence))
            and .65 <= p.visibility <= 1 and .65 <= p.presence <= 1
            and 0 <= p.x <= 1 and 0 <= p.y <= 1)


@dataclass(frozen=True)
class BodyFraming:
    target: tuple
    bounds: tuple
    head_landmark_visible: bool
    foot_tips_visible: bool
    fits_with_margin: bool
    points_with_margin: bool


def body_framing(pose):
    if pose is None or pose.landmarks_33 is None or len(pose.landmarks_33) != 33:
        return None
    points = pose.landmarks_33
    if any(not _visible(points[i]) for i in (11, 12, 23, 24, 27, 28)):
        return None
    head = _visible(points[0])
    feet = all(_visible(points[i]) for i in (29, 30, 31, 32))
    # Include visible head, hands and feet; an occluded hand need not stop tracking.
    points = tuple(p for p in points if _visible(p))
    left, top = min(p.x for p in points), min(p.y for p in points)
    right, bottom = max(p.x for p in points), max(p.y for p in points)
    return BodyFraming(((left + right) / 2, (top + bottom) / 2),
                       (left, top, right, bottom), head, feet,
                       right-left <= .88 and bottom-top <= .88,
                       head and feet and left >= .06 and top >= .06 and right <= .94 and bottom <= .94)


def full_body_target(pose):
    framing = body_framing(pose)
    return framing.target if framing else None


def framing_velocity(framing, settings=TrackingSpeeds()):
    """Keep the ordinary deadzone, but correct reliable points near an edge."""
    if framing is None:
        return 0.0, 0.0
    pitch, pan = tracking_velocity(framing.target, settings)
    edge_pitch, edge_pan = tracking_velocity(framing.target, replace(settings, deadzone=0))
    left, top, right, bottom = framing.bounds
    if left < .06 or right > .94:
        pan = edge_pan
    if top < .06 or bottom > .94:
        pitch = edge_pitch
    return pitch, pan


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
