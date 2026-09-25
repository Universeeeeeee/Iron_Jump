"""Tests for treadmill configuration models and type aliases."""

import pytest
from typing import get_args

from config.param_schema import get_schema
from config.test_config import AnyTestConfig, config_from_dict
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig


def test_any_test_config_includes_treadmill_configs():
    assert TreadmillGaitConfig in get_args(AnyTestConfig)
    assert TreadmillRunningConfig in get_args(AnyTestConfig)


def test_treadmill_gait_config_accepts_manual_speed_and_foot_snapshot():
    cfg = TreadmillGaitConfig(
        stop_type="End of Time",
        test_length="02:00",
        treadmill_speed=8.5,
        direction="Interface side",
        foot_length_cm_snapshot=26.0,
        foot_length_source="manual",
        min_step_length=20.0,
        automatic_data_filter=20,
    )

    assert cfg.test_type == "Treadmill Gait Test"
    assert cfg.treadmill_speed == 8.5
    assert cfg.foot_length_cm_snapshot == 26.0
    assert cfg.to_dict()["automatic_data_filter"] == 20


def test_treadmill_running_config_uses_gap_not_min_step_length():
    cfg = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=12.0,
        direction="Opposite side",
        foot_length_cm_snapshot=27.0,
        foot_length_source="captured",
        min_gap_between_feet=8.0,
    )

    assert cfg.test_type == "Treadmill Running Test"
    assert cfg.min_gap_between_feet == 8.0
    assert "min_step_length" not in cfg.to_dict()


def test_treadmill_configs_default_to_three_kmh_and_opposite_side():
    gait = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
    )
    running = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
    )

    assert gait.treadmill_speed == 3.0
    assert gait.direction == "Opposite side"
    assert running.treadmill_speed == 3.0
    assert running.direction == "Opposite side"


def test_treadmill_speed_range_is_validated():
    with pytest.raises(ValueError, match="treadmill_speed"):
        TreadmillRunningConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=25.0,
            direction="Interface side",
        )


def test_gait_automatic_data_filter_is_disabled_or_10_to_90():
    with pytest.raises(ValueError, match="automatic_data_filter"):
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=4.0,
            direction="Interface side",
            automatic_data_filter=5,
        )


def test_config_from_dict_passes_fields_through_as_is():
    cfg = config_from_dict(
        {
            "test_type": "Treadmill Gait Test",
            "stop_type": "Software command",
            "test_length": "02:00",
            "treadmill_speed": 5.0,
            "direction": "Interface side",
        }
    )

    assert isinstance(cfg, TreadmillGaitConfig)
    assert cfg.stop_type == "Software command"
    assert cfg.test_length == "02:00"
    assert cfg.treadmill_speed == 5.0
    assert cfg.direction == "Interface side"


def test_config_from_dict_returns_treadmill_config():
    cfg = config_from_dict(
        {
            "test_type": "Treadmill Gait Test",
            "stop_type": "Software command",
            "test_length": None,
            "treadmill_speed": 5.0,
            "direction": "Interface side",
        }
    )

    assert isinstance(cfg, TreadmillGaitConfig)


# ---- Schema filtering tests ----

def test_treadmill_gait_schema_has_min_step_length_not_min_gap():
    schema = get_schema()
    names = {param.name for param in schema.visible_params_for_test("Treadmill Gait Test")}

    assert "treadmill_speed" in names
    assert "direction" in names
    assert "min_step_length" in names
    assert "automatic_data_filter" in names
    assert "min_gap_between_feet" not in names


def test_treadmill_schema_uses_mode_specific_speeds_and_opposite_side():
    schema = get_schema()
    speed = schema.get_param_def("treadmill_speed")
    direction = schema.get_param_def("direction")

    assert speed is not None
    assert speed.default == {"Treadmill Gait Test": 3.0, "Treadmill Running Test": 6.0}
    assert direction is not None
    assert direction.default == "Opposite side"


def test_treadmill_running_schema_has_min_gap_not_automatic_filter():
    schema = get_schema()
    names = {param.name for param in schema.visible_params_for_test("Treadmill Running Test")}

    assert "treadmill_speed" in names
    assert "direction" in names
    assert "min_gap_between_feet" in names
    assert "automatic_data_filter" not in names
    assert "min_step_length" not in names
