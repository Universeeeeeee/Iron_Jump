"""Immutable software reaction records, retaining both unsynchronized clocks."""
from dataclasses import dataclass, field
import math
from statistics import median


@dataclass(frozen=True)
class ReactionTrialRecord:
    index: int
    modality: str
    action: str
    status: str
    stimulus_request_host_ns: int | None = None
    response_received_host_ns: int | None = None
    response_sample_index: int | None = None
    response_frame_index: int | None = None
    reaction_time_ms: float | None = None
    quality_flags: tuple[str, ...] = ()
    timing_method: str = "host_receive_minus_stimulus_request"
    timing_quality: str = "uncalibrated"
    actual_stimulus_onset_ns: int | None = None
    stream_id: str | None = None
    stimulus_scheduled_host_ns: int | None = None
    confirmation_sample_index: int | None = None
    confirmation_received_host_ns: int | None = None


def _statistics(trials):
    values = [trial.reaction_time_ms for trial in trials
              if trial.status == "valid" and trial.reaction_time_ms is not None]
    mean = sum(values) / len(values) if values else None
    return {
        "count": len(values), "mean_ms": mean,
        "median_ms": median(values) if values else None,
        "min_ms": min(values) if values else None,
        "max_ms": max(values) if values else None,
        "std_ms": math.sqrt(sum((value - mean) ** 2 for value in values) / len(values)) if values else None,
    }


@dataclass(frozen=True)
class ReactionTestReport:
    trials: tuple[ReactionTrialRecord, ...] = ()
    finish_reason: str = "manual"
    report_config_snapshot: dict = field(default_factory=dict)
    export_frames: tuple = ()
    export_timestamps: tuple = ()

    @property
    def attempts(self):
        return self.trials

    @property
    def valid_trials(self):
        return tuple(trial for trial in self.trials if trial.status == "valid")

    @property
    def valid_count(self):
        return len(self.valid_trials)

    @property
    def mean_reaction_time_ms(self):
        return _statistics(self.trials)["mean_ms"]

    @property
    def median_reaction_time_ms(self):
        return _statistics(self.trials)["median_ms"]

    @property
    def min_reaction_time_ms(self):
        return _statistics(self.trials)["min_ms"]

    @property
    def max_reaction_time_ms(self):
        return _statistics(self.trials)["max_ms"]

    @property
    def std_reaction_time_ms(self):
        return _statistics(self.trials)["std_ms"]

    @property
    def grouped_statistics(self):
        return {modality: _statistics(trial for trial in self.trials if trial.modality == modality)
                for modality in ("visual", "acoustic")}

    @property
    def timing_quality(self):
        return "uncalibrated"
