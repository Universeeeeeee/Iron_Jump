"""A local unresolved growth must not restart a remote reliable footprint."""
from dataclasses import replace

import pytest

from hardware.beam_filter import GroundStabilityFilter
from tests.test_overground_walking import processor, frame


def replay(*, filtered=False, reverse=False, kind='growth'):
    p = processor(3, stop_type='Software command', starting_foot='Left')
    optical = GroundStabilityFilter(p.device.layout)
    source = []
    for n in range(800):
        anchor_end = 275 if kind == 'anchor_absent' else 400
        groups = [(20, 40)] if kind != 'no_anchor' and 100 <= n < anchor_end else []
        second = 220 if kind == 'simultaneous' else 272
        join = 280 if kind == 'age' else 276
        if 220 <= n < join and not (kind == 'interruption' and n == 245):
            groups += [(85, 94)] if kind == 'historical_wide' and n < 230 else [(85, 90)]
        if second <= n < join:
            groups += [(100, 100)]
        if join <= n < 500:
            groups += [(85, 135)] if kind == 'wide_merge' else [(85, 105)]
        if kind == 'third' and 200 <= n < 450:
            groups += [(160, 180)]
        if kind == 'extra_pending' and 268 <= n < 290:
            groups += [(180, 180)]
        if 520 <= n < 650:
            groups += [(150, 170)]
        if 660 <= n < 750:
            groups += [(215, 235)]
        bits = bytearray(len(p.positions))
        for low, high in groups:
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        if reverse:
            bits.reverse()
        raw = replace(frame(p.device.layout, n), contact_bits=bytes(bits))
        source.append(raw.contact_bits)
        for measured in optical.feed(raw) if filtered else [raw]:
            p.process(measured)
        assert raw.contact_bits == source[-1]
    if filtered:
        for measured in optical.flush():
            p.process(measured)
    return p


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_local_growth_retains_remote_release_without_claiming_foot_identity(filtered, reverse):
    p = replay(filtered=filtered, reverse=reverse)
    assert not p.issues
    anchor = p.contacts[0]
    assert anchor.start == pytest.approx(.100) and anchor.end == pytest.approx(.400)
    assert anchor.confirmed and anchor.touch_known and anchor.position_known and not anchor.exclusion
    group = p.contacts[1]
    assert group.start == pytest.approx(.220) and group.end == pytest.approx(.500)
    assert group.observed_samples == 280  # overlapping sources cannot add votes
    assert group.exclusion == 'unresolved_coalescence'
    assert not group.touch_known and not group.position_known and group.side == 'unknown'
    row = next(d for d in p.summary()['candidate_decisions']
               if d['reason'] == 'unresolved_islands_coalesced')
    assert row['first_sample'] == 272 and row['observed_samples'] == 4
    assert row['outcome'] == 'unresolved' and row['owner_first_sample'] == 220
    assert p.summary()['valid_touches'] == 3
    assert [(s['from_id'], s['to_id']) for s in p.summary()['steps']] == [(2, 3)]
    assert p.summary()['duration_s'] == pytest.approx(.650)


@pytest.mark.parametrize('kind', ['simultaneous', 'third', 'age', 'interruption', 'no_anchor',
                                 'anchor_absent', 'historical_wide', 'wide_merge', 'extra_pending'])
def test_local_growth_cannot_hide_simultaneous_sources_or_extra_reliable_foot(kind):
    p = replay(kind=kind)
    assert any(i['code'] == 'ambiguous_contacts' for i in p.issues)
    assert not any(d['reason'] == 'unresolved_islands_coalesced'
                   for d in p.summary()['candidate_decisions'])


@pytest.mark.parametrize('filtered', [False, True])
def test_underwidth_unresolved_group_cannot_be_absorbed_then_bridge_step_time(filtered):
    p = processor(3, stop_type='Software command')
    optical = GroundStabilityFilter(p.device.layout)
    for n in range(700):
        groups = ([(60, 80)] if 100 <= n < 277 else
                  [(60, 95)] if 277 <= n < 400 else [])
        groups += [(90, 90)] if 220 <= n < 276 else []
        groups += [(95, 95)] if 272 <= n < 276 else []
        groups += [(90, 95)] if n == 276 else []
        groups += [(150, 170)] if 350 <= n < 500 else []
        groups += [(215, 235)] if 520 <= n < 650 else []
        bits = bytearray(len(p.positions))
        for low, high in groups:
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        raw = replace(frame(p.device.layout, n), contact_bits=bytes(bits))
        for measured in optical.feed(raw) if filtered else [raw]:
            p.process(measured)
    if filtered:
        for measured in optical.flush():
            p.process(measured)
    assert any(i['code'] == 'ambiguous_contacts' and i['frame_index'] == 276 for i in p.issues)
    assert not any(s['from_id'] == 0 for s in p.summary()['steps'])
