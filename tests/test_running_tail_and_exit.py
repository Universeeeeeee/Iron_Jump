"""Independent sample-clock truth for masked tails and terminal contact rolling."""
import pytest

from config.overground_running_config import OvergroundRunningConfig
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from engine.overground_session import OvergroundSession
from hardware.beam_quality import masked_frame
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice


def sample(layout, n, ranges=(), bits=None):
    if bits is None:
        bits = bytes(int(any(a <= x <= b for a, b in ranges)) for x in layout.positions_m)
    return SensorFrame('tail-exit', layout, n, n, (n + 1) * 1_000_000,
                       bytes(bits), b'\x01' * layout.bit_count, b'')


def masked_capture(end, *, neighbor=True, later=False, first_masked=False):
    layout = DeviceLayout.linear(8)
    device = PreparedDevice(layout, 'tail-exit', -1, 0, 3000, bad_indices=(576,))
    session = OvergroundSession(OvergroundRunningConfig(stop_type='Software command'),
                               OvergroundRunningProcessor)
    session.start_prepared(device)
    raw_bits = []
    for n in range(end):
        bits = bytearray(layout.bit_count)
        bits[576] = 1
        if 100 <= n < 300:
            if first_masked:
                bits[577:596] = b'\x01' * 19
            else:
                bits[20:41] = b'\x01' * 21
        if neighbor and 500 <= n < 900:
            low = 584 if n < 510 else 577
            bits[low:596] = b'\x01' * (596 - low)
        if later and 1100 <= n < 1300:
            bits[680:703] = b'\x01' * 23
        raw = sample(layout, n, bits=bits)
        raw_bits.append(raw.contact_bits)
        session.on_frame(masked_frame(raw, device.bad_indices), raw_frame=raw)
    session.halt()
    report = session.build_report('manual')
    assert report.export_frames == tuple(raw_bits)
    return session.processor, report.running_summary, raw_bits


@pytest.mark.parametrize('end', [750, 1000])
def test_masked_tail_has_missing_duration_and_keeps_raw_frames(qtbot, end):
    p, s, raw = masked_capture(end)
    occupied = [n for n, bits in enumerate(raw) if any(b for i, b in enumerate(bits) if i != 576)]
    assert occupied[0] == 100 and occupied[-1] == min(end, 900) - 1
    assert s['duration_s'] is None
    assert s['contacts'][0]['contact_s']['value'] == pytest.approx(.2)
    assert not s['valid_cycles']
    assert any(i['code'] == 'masked_contact_boundary' for i in p.issues)


def test_later_complete_contact_restores_duration_without_bridging_mask(qtbot):
    p, s, raw = masked_capture(1500, later=True)
    assert raw[1299][680] and not raw[1300][680]
    assert s['duration_s'] == pytest.approx(1.2)
    assert p.contacts[-1].end == 1300
    assert not s['valid_cycles']
    assert p.contacts[-1].side == 'unknown'


def test_bad_bit_without_neighbor_activity_does_not_censor_duration(qtbot):
    p, s, _ = masked_capture(1000, neighbor=False)
    assert not p.issues
    assert s['duration_s'] == pytest.approx(.2)


def test_masked_first_activity_cannot_recover_passage_origin_from_later_contact(qtbot):
    p, s, raw = masked_capture(1500, neighbor=False, later=True, first_masked=True)
    assert raw[100][577] and raw[299][577]
    assert not raw[300][577]
    assert s['duration_s'] is None
    assert s['contacts'][-1]['contact_s']['valid']
    assert s['contacts'][-1]['contact_s']['value'] == pytest.approx(.2)
    assert p.contacts[-1].start == 1100 and p.contacts[-1].end == 1300


def exit_capture(reverse=False, revoke=None, *, segments=1, session=None):
    layout = DeviceLayout.linear(segments)
    p = OvergroundRunningProcessor(OvergroundRunningConfig(),
                                   PreparedDevice(layout, 'tail-exit', -1, 0, 3000))
    if session is not None:
        session.start_prepared(p.device)
        p = session.processor
    for n in range(1700):
        bounds = []
        if 100 <= n < 250:
            bounds = [(.15, .3)]
        elif 400 <= n < 550:
            bounds = [(.45, .6)]
        elif 700 <= n < 920:
            offset = segments - 1
            bounds = [(offset + .82, offset + (.99 if 820 <= n < 840 and revoke != 'never_terminal' else .96))]
        if revoke == 'interior' and 1000 <= n < 1150:
            bounds = [(.78, .93)]
        if revoke == 'turn' and 1000 <= n < 1150:
            bounds = [(.4, .55)]
        if revoke == 'ambiguity' and 860 <= n < 900:
            bounds = [(.1, .99)]
        if revoke == 'short_clear' and 860 <= n < 862:
            bounds = []
        if reverse:
            bounds = [(layout.positions_m[-1] - b, layout.positions_m[-1] - a) for a, b in bounds]
        if revoke == 'gap' and n == 860:
            continue
        if revoke == 'disconnect' and n == 860:
            p.break_continuity('disconnected', n)
            break
        f = sample(layout, n, bounds)
        if session is None:
            p.process(f)
        else:
            session.on_frame(f)
    return p


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('segments', [1, 3, 8, 12])
def test_confirmed_terminal_contact_roll_keeps_exit_evidence(reverse, segments):
    p = exit_capture(reverse, segments=segments)
    assert len(p.contacts) == 3
    assert p.contacts[-1].end == 920
    assert p.finished_reason == 'passage_complete'
    assert p.last_sample == 1419  # 500 empty samples starting at 920.


@pytest.mark.parametrize('reverse', [False, True])
def test_formal_filtered_session_keeps_terminal_contact_evidence(qtbot, reverse):
    session = OvergroundSession(OvergroundRunningConfig(), OvergroundRunningProcessor)
    p = exit_capture(reverse, session=session)
    assert session.done
    assert p.finished_reason == 'passage_complete'
    assert p.contacts[-1].end == 920
    assert p.last_sample == 1419


@pytest.mark.parametrize('revoke', ['interior', 'turn', 'ambiguity', 'gap', 'disconnect', 'never_terminal', 'short_clear'])
def test_exit_requires_continuous_terminal_contact_identity(revoke):
    p = exit_capture(revoke=revoke)
    assert p.finished_reason != 'passage_complete'
    assert not p._exit_evidence
    if revoke == 'turn':
        assert p.finished_reason == 'turn_detected'


def overlapping_exit_capture(reverse, old_lift, *, new_interior=False, session=None):
    layout = DeviceLayout.linear(1)
    p = OvergroundRunningProcessor(OvergroundRunningConfig(),
                                   PreparedDevice(layout, 'tail-exit', -1, 0, 3000))
    if session is not None:
        session.start_prepared(p.device)
        p = session.processor
    for n in range(1800):
        bounds = []
        if 100 <= n < 250:
            bounds.append((.15, .3))
        if 400 <= n < old_lift:
            bounds.append((.45, .6))
        if 700 <= n < 920:
            bounds.append((.82, .99 if 820 <= n < 840 else .96))
        # A new interior candidate after terminal confirmation must revoke the
        # proof, including when the terminal foot remains at the endpoint.
        if new_interior and 910 <= n < 1080:
            bounds.append((.45, .6))
            if n < 920:
                bounds[-2] = (.82, .99)
        if reverse:
            bounds = [(layout.positions_m[-1] - b, layout.positions_m[-1] - a) for a, b in bounds]
        f = sample(layout, n, bounds)
        if session is None:
            p.process(f)
        else:
            session.on_frame(f)
    return p


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('old_lift', [900, 1000])
@pytest.mark.parametrize('filtered', [False, True])
def test_terminal_proof_survives_preexisting_other_foot_support(qtbot, reverse, old_lift, filtered):
    session = OvergroundSession(OvergroundRunningConfig(), OvergroundRunningProcessor) if filtered else None
    p = overlapping_exit_capture(reverse, old_lift, session=session)
    assert len(p.contacts) == 3
    assert all(c.confirmed and not c.problem and not c.interrupted for c in p.contacts)
    assert p.contacts[-1].end == 920
    assert p.finished_reason == 'passage_complete'
    assert p.last_sample == max(old_lift, 920) + 499


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('filtered', [False, True])
def test_new_interior_contact_during_terminal_stance_revokes_proof(qtbot, reverse, filtered):
    session = OvergroundSession(OvergroundRunningConfig(), OvergroundRunningProcessor) if filtered else None
    p = overlapping_exit_capture(reverse, 880, new_interior=True, session=session)
    assert len(p.contacts) == 4
    assert p.finished_reason != 'passage_complete'
    assert not p._exit_evidence
