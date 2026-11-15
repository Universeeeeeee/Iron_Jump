"""Device-quality policy; no model or UI code may override a session snapshot."""
from dataclasses import asdict, dataclass, replace
import math


@dataclass(frozen=True)
class BeamQualityPolicy:
    max_bad_ratio: float = 0.025
    max_consecutive: int = 2
    observation_seconds: float = 3.0

    def __post_init__(self):
        if not math.isfinite(self.max_bad_ratio) or not 0 <= self.max_bad_ratio <= 0.1:
            raise ValueError("异常比例必须在 0–10% 之间")
        if type(self.max_consecutive) is not int or not 0 <= self.max_consecutive <= 10:
            raise ValueError("连续异常上限必须在 0–10 之间")
        if not math.isfinite(self.observation_seconds) or not 1 <= self.observation_seconds <= 30:
            raise ValueError("观察时长必须在 1–30 秒之间")

    @property
    def samples(self):
        return math.ceil(self.observation_seconds * 1000)

    def snapshot(self):
        return asdict(self)


def longest_run(indices, layout):
    positions = layout.positions_m
    longest = run = 0
    previous = None
    for i in sorted(indices):
        adjacent = (previous is not None and i == previous + 1 and
                    positions[i] - positions[previous] <= 1.5 * max(
                        layout.segments[i // 96].pitch_m, layout.segments[previous // 96].pitch_m))
        run = run + 1 if adjacent else 1
        longest = max(longest, run)
        previous = i
    return longest


def masked_frame(frame, indices):
    bits = bytearray(frame.contact_bits)
    for index in indices:
        bits[index] = 0
    return replace(frame, contact_bits=bytes(bits))


def uncertain_contact(frame, indices):
    """Do not join contact across an unavailable beam or trust its moving edge."""
    positions = frame.layout.positions_m
    for i in indices:
        for j in (i - 1, i + 1):
            if (0 <= j < len(frame.contact_bits) and j not in indices and frame.contact_bits[j]
                    and abs(positions[j] - positions[i]) <= 0.04):
                return True
    return False
