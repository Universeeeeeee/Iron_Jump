"""Operator-owned settings, intentionally separate from model configuration."""
from qtpy.QtCore import QSettings
from hardware.beam_quality import BeamQualityPolicy


def load_policy(settings=None):
    settings = settings or QSettings("IronJump", "DeviceQuality")
    try:
        return BeamQualityPolicy(
            float(settings.value("max_bad_ratio", .025)),
            int(settings.value("max_consecutive", 2)),
            float(settings.value("observation_seconds", 3.0)))
    except (TypeError, ValueError):
        return BeamQualityPolicy()


def save_policy(policy, settings=None):
    settings = settings or QSettings("IronJump", "DeviceQuality")
    for key, value in policy.snapshot().items():
        settings.setValue(key, value)
    settings.sync()
