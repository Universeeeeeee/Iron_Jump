"""Configuration for host-estimated, single-module reaction trials."""
from dataclasses import asdict, dataclass, field
import re


@dataclass(frozen=True)
class ReactionConfig:
    test_type: str = field(default="Reaction Times", init=False)
    stimulus_type: str = "Visual stimulus"
    start_position: str = "Inside area"
    number_of_repetitions: int = 5
    sequence_type: str = "Automatic"
    minimum_pause: str = "00:02"
    stimulus_delay_min_ms: int = 2000
    stimulus_delay_max_ms: int = 5000
    ready_hold_ms: int = 500
    confirmation_ms: int = 10
    response_timeout_ms: int = 3000

    def to_dict(self):
        return asdict(self)

    @property
    def mode_label(self):
        return "反应时"

    @property
    def minimum_pause_ms(self):
        minutes, seconds = self.minimum_pause.split(":")
        return (int(minutes) * 60 + int(seconds)) * 1000


def validate_reaction_config(config):
    errors = []
    choices = {
        "stimulus_type": {"Visual stimulus", "Acoustic stimulus", "Visual/Acoustic stimulus"},
        "start_position": {"Inside area", "Outside area"},
        "sequence_type": {"Automatic", "Manual"},
    }
    for name, allowed in choices.items():
        value = getattr(config, name, None)
        if not isinstance(value, str) or value not in allowed:
            errors.append(f"{name} 的选项无效。")
    repetitions = getattr(config, "number_of_repetitions", None)
    if type(repetitions) is not int or not 1 <= repetitions <= 99:
        errors.append("反应时重复次数必须为 1–99 的整数。")
    pause = getattr(config, "minimum_pause", None)
    if not isinstance(pause, str) or re.fullmatch(r"[0-5]\d:[0-5]\d", pause) is None:
        errors.append("最小休息时间必须为 00:00–59:59。")
    valid_times = True
    for name in ("stimulus_delay_min_ms", "stimulus_delay_max_ms", "ready_hold_ms",
                 "confirmation_ms", "response_timeout_ms"):
        value = getattr(config, name, None)
        if type(value) is not int or value <= 0:
            errors.append(f"{name} 必须为正整数毫秒。")
            valid_times = False
    if valid_times and config.stimulus_delay_min_ms > config.stimulus_delay_max_ms:
        errors.append("刺激等待下限不能超过上限。")
    return errors
