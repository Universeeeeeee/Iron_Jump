"""Overground evidence regressions, with device samples as the independent clock."""
from dataclasses import replace

import pytest

from tests.test_overground_walking import CONTACTS, frame, processor, walk


def test_identity_and_direction_follow_touch_order_not_confirmation_order():
    p = processor(stop_type="Software command", starting_foot="Left")
    for n in range(500):
        ranges = []
        if 100 <= n < 400:
            ranges.append((.33, .37) if n < 300 else (.25, .45))
        if 200 <= n < 450:
            ranges.append((.85, 1.05))
        p.process(frame(p.device.layout, n, ranges))
        if n == 280:
            assert p.contacts[1].confirmed
            assert p.contacts[1].side == "unknown"
            assert p.origin is None
    assert [(c.start, c.label, c.side) for c in p.contacts] == [
        (.1, "A", "left"), (.2, "B", "right")]
    assert p.contacts[0].confirmed_at > p.contacts[1].confirmed_at
    assert p.origin == .1
    assert p.direction == 1
    assert p.finished_reason is None


def test_one_beam_edges_survive_footprint_validation():
    p = processor(stop_type="Software command")
    for n in range(320):
        bits = bytearray(len(p.positions))
        if 100 <= n < 300:
            bits[30] = 1
        if 110 <= n < 290:
            bits[30:45] = bytes([1]) * 15
        p.process(replace(frame(p.device.layout, n), contact_bits=bytes(bits)))
    assert len(p.contacts) == 1
    assert p.contacts[0].start == .1
    assert p.contacts[0].end == .3
    assert p.summary()["mean_contact_s"] == pytest.approx(.2)


@pytest.mark.parametrize("gap", [9, 10, 11])
def test_release_threshold_and_merge_audit(gap):
    p = processor(stop_type="Software command")
    walk(p, [(100, 200, .35), (200 + gap, 350, .35)], 370)
    if gap < p.config.release_ms:
        assert len(p.contacts) == 1
        c = p.summary()["contacts"][0]
        assert c["merged_interruptions"] == [
            {"start_sample": 200, "end_sample": 200 + gap, "reason": "release_debounce"}]
        assert c["observed_samples"] == 250 - gap
        assert c["end"] - c["start"] == pytest.approx(.25)
    else:
        assert len(p.contacts) == 2
        assert p.contacts[0].end == .2
        assert p.contacts[1].start == (200 + gap) / 1000


def test_single_beam_at_lane_boundary_prevents_complete_contact():
    p = processor(stop_type="Software command")
    for n in range(320):
        bits = bytearray(len(p.positions))
        if 100 <= n < 300:
            bits[1:16] = bytes([1]) * 15
        if n == 100:
            bits[0] = 1
            bits[1:16] = bytes(15)
        p.process(replace(frame(p.device.layout, n), contact_bits=bytes(bits)))
    assert p.contacts[0].start == .1
    assert p.contacts[0].exclusion == "boundary_contact"
    assert p.summary()["mean_contact_s"] is None


def test_simultaneous_touches_stay_unknown_despite_different_confirmation_times():
    p = processor(stop_type="Software command", starting_foot="Left")
    for n in range(420):
        ranges = []
        if 100 <= n < 400:
            ranges = [(.33, .37) if n < 300 else (.25, .45), (.85, 1.05)]
        p.process(frame(p.device.layout, n, ranges))
    assert all(c.side == "unknown" and c.exclusion == "simultaneous_contacts" for c in p.contacts)
    assert p.summary()["valid_cycles"] == 0


@pytest.mark.parametrize("segments", [3, 8, 12])
@pytest.mark.parametrize("reverse", [False, True])
def test_cycle_support_matches_independent_raw_occupancy(segments, reverse):
    p = processor(segments, stop_type="Software command", starting_foot="Left")
    contacts = [(start, end, 2.5 - pos if reverse else pos) for start, end, pos in CONTACTS]
    walk(p, contacts, 2400)
    cycles = p.summary()["cycles"]
    assert len(cycles) == 2
    for i, cycle in enumerate(cycles):
        start, end = contacts[i][0], contacts[i + 2][0]
        occupancy = [sum(a <= n < b for a, b, _ in contacts) for n in range(start, end)]
        assert cycle["duration_s"] == pytest.approx((end - start) / 1000)
        assert cycle["single_support_s"] == pytest.approx(occupancy.count(1) / 1000)
        assert cycle["double_support_s"] == pytest.approx(occupancy.count(2) / 1000)
    assert p.direction == (-1 if reverse else 1)


def test_dropped_samples_cannot_be_recorded_as_debounce_merge():
    p = processor(stop_type="Software command", starting_foot="Left")
    walk(p, [(100, 350, .35)], 370, skip=range(200, 209))
    assert len(p.contacts) == 2
    assert all(not c.merged_interruptions for c in p.contacts)
    assert p.summary()["mean_contact_s"] is None


def test_debounce_wait_does_not_count_as_observed_samples():
    p = processor(stop_type="Software command", min_contact_time=1, confirmation_ms=8)
    walk(p, [(100, 101, .35), (106, 107, .35), (112, 113, .35)], 130)
    assert len(p.contacts) == 1
    assert p.contacts[0].observed_samples == 3
    assert not p.contacts[0].confirmed
    assert p.summary()["mean_contact_s"] is None


def test_pending_earlier_candidate_blocks_report_until_rejected():
    p = processor(stop_type="Software command", starting_foot="Left")
    for n in range(420):
        ranges = [(.33, .37)] if 100 <= n < 400 else []
        if 200 <= n < 300:
            ranges.append((.85, 1.05))
        p.process(frame(p.device.layout, n, ranges))
        if n == 350:
            s = p.summary()
            assert p.origin is None
            assert s["contacts"][1]["exclusion"] == "pending_touch_order"
            assert s["mean_contact_s"] is None
    assert p.contacts[0].exclusion == "short_contact"
    assert p.origin == .2
    assert p.contacts[1].side == "unknown"
    assert p.summary()["mean_contact_s"] == pytest.approx(.1)


def test_confirmation_on_same_sample_does_not_mean_simultaneous_touch():
    p = processor(stop_type="Software command", starting_foot="Left")
    for n in range(420):
        ranges = []
        if 100 <= n < 400:
            ranges.append((.33, .37) if n < 259 else (.25, .45))
        if 200 <= n < 400:
            ranges.append((.85, 1.05))
        p.process(frame(p.device.layout, n, ranges))
    assert p.contacts[0].confirmed_at == p.contacts[1].confirmed_at
    assert [c.side for c in p.contacts] == ["left", "right"]
    assert all(c.exclusion is None for c in p.contacts)


def test_saved_report_preserves_correction_and_both_event_times():
    from data.subject_store import _report_detail, _report_from_detail

    p = processor(stop_type="Software command")
    walk(p, [(100, 200, .35), (209, 350, .35)], 370)
    report = p.build_report("manual")
    restored = _report_from_detail(_report_detail(report))
    assert restored.walking_summary == report.walking_summary
    c = restored.walking_summary["contacts"][0]
    assert c["confirmed_at"] > c["start"]
    assert c["lift_confirmed_at"] > c["end"]
    assert c["merged_interruptions"][0]["end_sample"] == 209
