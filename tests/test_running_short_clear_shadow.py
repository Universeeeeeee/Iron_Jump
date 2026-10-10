"""A returning foot must not replace the per-frame masked group collection."""
from dataclasses import replace

import pytest

from engine.modes.overground_running_processor import OvergroundRunningProcessor
from engine.overground_session import OvergroundSession
from hardware.beam_quality import masked_frame, uncertain_contact
from hardware.walking_preflight import PreparedDevice
from tests.test_overground_running import frame, processor


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('masked_second', [False, True])
def test_short_clear_return_with_second_foot_keeps_local_quality(qtbot, filtered, masked_second):
    p = processor(8, min_contact_time=20, starting_foot='Left')
    bad = (576,) if masked_second else ()
    device = PreparedDevice(p.device.layout, 'running', -1, 0, 1000, bad_indices=bad)
    p = OvergroundRunningProcessor(p.config, device)
    session = OvergroundSession(p.config, type(p)) if filtered else None
    if session:
        session.start_prepared(device)
    raw = []
    for n in range(450):
        ranges = []
        if 100 <= n < 250 and n != 200:
            # Distinct old/new beams keep the 1 ms full-clear event visible
            # after per-beam confirmation, while the same-foot match survives.
            ranges = [(.2, .23) if n < 200 else (.25, .27)] if filtered else [(.2, .4)]
        if 201 <= n < 350:
            ranges += [(6.0104, 6.2)] if masked_second else [(.8, 1.0)]
        f = frame(device.layout, n, ranges)
        if bad:
            bits = bytearray(f.contact_bits)
            bits[576] = 1
            f = replace(f, contact_bits=bytes(bits))
        raw.append(f.contact_bits)
        measurement = masked_frame(f, bad)
        if session:
            session.on_frame(measurement, raw_frame=f)
        else:
            p.process(measurement, masked_contact=uncertain_contact(measurement, bad))
    if session:
        session.halt()
        p = session.processor
        assert session.build_report('manual').export_frames == tuple(raw)
    assert len(p.contacts) == 2
    first, second = p.contacts
    assert first.first_uncertain_sample == 200
    assert first.problem == 'uncertain_short_clear'
    assert second.start == 201 and second.side == 'unknown'
    rows = p.summary()['contacts']
    assert rows[0]['touch_s']['valid']
    assert rows[0]['contact_s']['missing_reason'] == 'uncertain_short_clear'
    assert not p.summary()['steps'][0]['time_s']['valid']
    if masked_second:
        assert second.interrupted == 'masked_contact_boundary'
        assert second.end is None
        assert rows[1]['contact_s']['missing_reason'] == 'masked_contact_boundary'
        assert not rows[1]['toe_m']['valid']
    else:
        assert second.end == 350 and second.confirmed
        assert rows[1]['contact_s']['valid']
        assert rows[1]['contact_s']['value'] == pytest.approx(.149)
