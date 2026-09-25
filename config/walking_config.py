"""Configuration for one overground walking passage (independent of treadmill)."""
from dataclasses import asdict, dataclass, field


@dataclass
class WalkingConfig:
    test_type: str = field(default="Sprint and Gait Test", init=False)
    stop_type: str = "Status change"
    starting_foot: str = "Not defined"
    min_contact_time: int = 60
    confirmation_ms: int = 8
    release_ms: int = 10
    exit_clear_ms: int = 500
    stop_threshold_s: float = 2.0

    def to_dict(self):
        return asdict(self)

    @property
    def mode_label(self):
        return "地面走路"

    @property
    def has_auto_stop(self):
        return self.stop_type == "Status change"
