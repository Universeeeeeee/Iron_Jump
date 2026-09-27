from __future__ import annotations

import pytest

from vision.foot_reference import FootLabel
from vision.phase_resync import (
    DeviceAnomalyDetector,
    DeviceLabelMapper,
    DevicePhaseInput,
    FootPhaseManager,
    PhaseState,
)


def _event(
    event_id: int,
    device: FootLabel,
    visual: FootLabel,
    *,
    anomaly: bool = False,
) -> DevicePhaseInput:
    return DevicePhaseInput(
        event_id=event_id,
        raw_device_symbol="A" if device is FootLabel.LEFT else "B",
        raw_device_label=device,
        visual_label=visual,
        device_anomaly=anomaly,
    )


def test_phase_flip_requires_crossed_opposite_device_labels():
    manager = FootPhaseManager()
    assert manager.process(_event(1, FootLabel.LEFT, FootLabel.RIGHT)) == ()
    finalized = manager.process(_event(2, FootLabel.RIGHT, FootLabel.LEFT))

    assert [item.final_label for item in finalized] == [FootLabel.RIGHT, FootLabel.LEFT]
    assert finalized[-1].phase_action == "auto_flip"
    assert finalized[-1].phase_flip_start_event_id == 1
    assert finalized[-1].phase_flip_confirm_event_id == 2
    assert manager.phase_offset is True
    assert manager.phase_epoch == 1


def test_same_device_double_mismatch_never_confirms():
    manager = FootPhaseManager()
    manager.process(_event(1, FootLabel.LEFT, FootLabel.RIGHT))
    assert manager.process(_event(2, FootLabel.LEFT, FootLabel.RIGHT)) == ()
    flushed = manager.flush()

    assert [item.final_label for item in flushed] == [FootLabel.LEFT, FootLabel.LEFT]
    assert flushed[1].phase_action == "same_device_mismatch_not_confirming"
    assert manager.phase_offset is False


def test_two_unknowns_preserve_suspect_and_third_expires():
    manager = FootPhaseManager()
    manager.process(_event(1, FootLabel.LEFT, FootLabel.RIGHT))
    manager.process(_event(2, FootLabel.RIGHT, FootLabel.UNKNOWN))
    manager.process(_event(3, FootLabel.LEFT, FootLabel.UNKNOWN))
    finalized = manager.process(_event(4, FootLabel.RIGHT, FootLabel.UNKNOWN))

    assert len(finalized) == 4
    assert manager.state is PhaseState.NORMAL
    assert manager.phase_offset is False


def test_agreement_cancels_pending_phase_flip():
    manager = FootPhaseManager()
    manager.process(_event(1, FootLabel.LEFT, FootLabel.RIGHT))
    finalized = manager.process(_event(2, FootLabel.RIGHT, FootLabel.RIGHT))

    assert len(finalized) == 2
    assert manager.phase_offset is False
    assert manager.state is PhaseState.NORMAL


def test_anomaly_alone_cannot_flip():
    manager = FootPhaseManager()
    first = manager.process(
        _event(1, FootLabel.LEFT, FootLabel.UNKNOWN, anomaly=True)
    )
    second = manager.process(
        _event(2, FootLabel.RIGHT, FootLabel.UNKNOWN, anomaly=True)
    )

    assert len(first) == len(second) == 1
    assert manager.phase_offset is False
    assert manager.state is PhaseState.NORMAL


def test_manual_flip_without_pending_applies_from_next_event():
    manager = FootPhaseManager()
    assert manager.manual_flip() == ()
    finalized = manager.process(_event(1, FootLabel.LEFT, FootLabel.UNKNOWN))

    assert finalized[0].final_label is FootLabel.RIGHT
    assert finalized[0].phase_action == "manual_flip"
    assert finalized[0].phase_flip_reason == "manual"


def test_manual_flip_relabels_only_pending_window_and_keeps_raw_label():
    manager = FootPhaseManager()
    manager.process(_event(1, FootLabel.LEFT, FootLabel.RIGHT))
    finalized = manager.manual_flip()

    assert len(finalized) == 1
    assert finalized[0].raw_device_label is FootLabel.LEFT
    assert finalized[0].final_label is FootLabel.RIGHT
    assert finalized[0].phase_flip_start_event_id == 1
    assert manager.phase_epoch == 1


def test_pending_contact_hard_limit_expires_without_flip():
    manager = FootPhaseManager()
    manager.process(_event(1, FootLabel.LEFT, FootLabel.RIGHT))
    manager.process(_event(2, FootLabel.LEFT, FootLabel.RIGHT))
    manager.process(_event(3, FootLabel.LEFT, FootLabel.RIGHT))
    manager.process(_event(4, FootLabel.LEFT, FootLabel.RIGHT))
    finalized = manager.process(_event(5, FootLabel.LEFT, FootLabel.RIGHT))

    assert len(finalized) == 5
    assert manager.phase_offset is False
    assert manager.state is PhaseState.NORMAL


@pytest.mark.parametrize("confirm_contact, expected_flip", [(4, True), (5, False)])
def test_cross_pair_must_confirm_within_contact_limit(confirm_contact, expected_flip):
    manager = FootPhaseManager()
    manager.process(_event(1, FootLabel.LEFT, FootLabel.RIGHT))
    for event_id in range(2, confirm_contact):
        manager.process(_event(event_id, FootLabel.LEFT, FootLabel.RIGHT))
    finalized = manager.process(
        _event(confirm_contact, FootLabel.RIGHT, FootLabel.LEFT)
    )

    assert manager.phase_offset is expected_flip
    assert any(item.phase_action == "auto_flip" for item in finalized) is expected_flip


def test_independent_confirmed_slips_increment_phase_epoch():
    manager = FootPhaseManager()
    manager.process(_event(1, FootLabel.LEFT, FootLabel.RIGHT))
    manager.process(_event(2, FootLabel.RIGHT, FootLabel.LEFT))
    manager.process(_event(3, FootLabel.LEFT, FootLabel.LEFT))
    finalized = manager.process(_event(4, FootLabel.RIGHT, FootLabel.RIGHT))

    assert finalized[-1].phase_action == "auto_flip"
    assert manager.phase_epoch == 2
    assert manager.phase_offset is False


def test_label_mapper_honors_first_symbol_starting_foot():
    mapper = DeviceLabelMapper("right")
    assert mapper.map("B") is FootLabel.RIGHT
    assert mapper.map("A") is FootLabel.LEFT
    assert DeviceLabelMapper().map("A") is FootLabel.LEFT


def test_anomaly_detector_uses_repetition_confidence_and_interval_baseline():
    detector = DeviceAnomalyDetector()
    detector.observe(FootLabel.LEFT, 0.0)
    anomaly, reasons = detector.observe(FootLabel.LEFT, 1.0, label_confidence=0.5)
    assert anomaly
    assert "repeated_device_label" in reasons
    assert "device_label_confidence_low" in reasons

    detector = DeviceAnomalyDetector()
    for index in range(7):
        detector.observe(
            FootLabel.LEFT if index % 2 == 0 else FootLabel.RIGHT,
            float(index),
        )
    anomaly, reasons = detector.observe(FootLabel.RIGHT, 6.2)
    assert anomaly
    assert "short_interval_duplicate_suspect" in reasons
