"""Running metrics use SI units and retain independent validity/reasons."""
from dataclasses import dataclass, field


@dataclass
class OvergroundRunningReport:
    touch_count: int = 0
    lift_count: int = 0
    finish_reason: str = "manual"
    running_summary: dict = field(default_factory=dict)
    report_config_snapshot: dict = field(default_factory=dict)
    visual_timeline: tuple = ()
    export_frames: tuple = ()
    export_timestamps: tuple = ()

    def __post_init__(self):
        from engine.ground_metric_completion import complete_ground_metrics
        self.running_summary = complete_ground_metrics(self.running_summary, 'run')
