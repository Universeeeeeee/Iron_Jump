"""Independent configuration for a single overground running passage."""
from dataclasses import asdict, dataclass, field


@dataclass
class OvergroundRunningConfig:
    test_type: str = field(default="Overground Running Test", init=False)
    stop_type: str = "Status change"
    starting_foot: str = "Not defined"
    min_contact_time: int = 20
    confirmation_ms: int = 3
    release_ms: int = 3
    toe_platform_ms: int = 5
    exit_clear_ms: int = 500
    stop_threshold_s: float = 2.0

    def to_dict(self):
        return asdict(self)

    @property
    def mode_label(self):
        return "地面跑步"

    @property
    def has_auto_stop(self):
        return self.stop_type == "Status change"
