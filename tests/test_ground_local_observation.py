"""Independent trajectories and device-clock regressions for local unknowns."""
from dataclasses import replace
import time

import pytest

from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.device_quality_session import DeviceQualitySession
from hardware.beam_quality import BeamQualityPolicy
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice
from hardware.ground_observation import GroundObservationModel
from engine.modes.walking_processor import WalkingProcessor
from engine.modes.overground_running_processor import OvergroundRunningProcessor


def sample(n, contacts=(), zero_segments=(), layout=None):
    layout = layout or DeviceLayout.linear(8)
    bits = bytearray(int(any(lo <= x <= hi for lo, hi in contacts)) for x in layout.positions_m)
    for s in zero_segments:
        bits[s * 96:(s + 1) * 96] = b'\x01' * 96
    return SensorFrame('local', layout, n, n, time.perf_counter_ns(), bytes(bits),
                       b'\x01' * layout.bit_count, b'')


@pytest.mark.parametrize('config', [WalkingConfig(), OvergroundRunningConfig()])
def test_remote_flicker_does_not_gate_all_ground_contacts(qtbot, config):
    gate = DeviceQualitySession(config, BeamQualityPolicy(observation_seconds=1))
    for n in range(1000):
        gate.on_frame(sample(n))
    gate.arm_checked((gate.preflight.context.key, False))
    delivered = []
    gate.frame_ready.connect(lambda raw, frame, uncertain: delivered.append((raw, frame, uncertain)))
    for n in range(1000, 2300):
        gate.on_frame(sample(n, [(.2, .38)] if n < 1600 else [], [7] if n % 6 == 0 else []))
    assert not any(uncertain for _, _, uncertain in delivered)
    assert all(all(frame.valid_bits) for _, frame, _ in delivered)
    assert any(all(frame.contact_bits[672:]) for _, frame, _ in delivered)
    assert all(all(frame.valid_bits[:96]) for _, frame, _ in delivered)
    gate.halt()


def processor(mode, **kwargs):
    layout = DeviceLayout.linear(8)
    device = PreparedDevice(layout, 'local', -1, 0, 1000)
    factory, config = ((WalkingProcessor, WalkingConfig) if mode == 'walk' else
                       (OvergroundRunningProcessor, OvergroundRunningConfig))
    return factory(config(stop_type='Software command', **kwargs), device)


def replay(p, frames):
    model = GroundObservationModel(p.device.layout, p.device.bad_indices,
                                   .18 if p.name == 'overground_walking' else .035)
    observations = []
    for frame in frames:
        observations.extend(model.feed(frame))
    observations.extend(model.flush())
    for obs in observations:
        p.process(obs.frame, obs)
    return model, observations


def time_ms(p, c, name):
    return getattr(c, name) * (1000 if p.name == 'overground_walking' else 1)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_clean_results_and_real_short_clear_preserve_mode_rules(mode):
    direct, local = processor(mode), processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 399 else
                     [(.62, .8)] if 400 <= n < 699 else
                     [(1.02, 1.2)] if 700 <= n < 1000 else []) for n in range(1100)]
    for f in frames:
        direct.process(f)
    replay(local, frames)
    a, b = direct.summary(), local.summary()
    for key in ['valid_steps', 'valid_cycles', 'duration_s', 'steps', 'cycles', 'step_lengths_m']:
        assert a[key] == b[key]
    assert [time_ms(local, c, 'start') for c in local.contacts] == [100, 400, 700]


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('length', range(1, 11))
@pytest.mark.parametrize('boundary', [100, 300])
def test_midpoint_edges_have_bounded_error_and_no_confirmation_delay(mode, length, boundary):
    # Independent truth: contact [100,300), erasure straddles its boundary.
    start = boundary - length // 2
    frames = [sample(n, [(.2, .38)] if 100 <= n < 300 else [],
                     [0] if start <= n < start + length else []) for n in range(340)]
    p = processor(mode)
    model, observations = replay(p, frames)
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    c = p.contacts[0]
    estimate = (start - 1 + start + length) / 2
    assert time_ms(p, c, 'start' if boundary == 100 else 'end') == pytest.approx(estimate)
    assert abs(estimate - boundary) <= (length + 1) / 2
    assert c.observed_samples == sum(100 <= n < 300 and not start <= n < start + length for n in range(340))
    assert not getattr(c, 'exclusion', None) and not getattr(c, 'interrupted', None)
    assert len(observations) == len(frames)
    assert model.audit[0]['recovered']
    assert all(obs.frame.wire_payload == frames[i].wire_payload for i, obs in enumerate(observations))


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_repeated_noise_inside_contact_and_after_release_does_not_latch(mode):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 300 else [], [0] if n % 6 == 0 else [])
              for n in range(360)]
    model, _ = replay(p, frames)
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    assert time_ms(p, p.contacts[0], 'end') <= 303
    assert not p.active
    assert p.contacts[0].observed_samples < 200
    assert model.interval_count > 50


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_remote_suffix_noise_preserves_real_foot_and_raw_samples(mode):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 300 else [],
                     [5, 6, 7] if n % 6 == 0 else []) for n in range(350)]
    original = tuple(f.contact_bits for f in frames)
    replay(p, frames)
    assert len(p.contacts) == 1
    c = p.contacts[0]
    assert time_ms(p, c, 'start') == 100 and time_ms(p, c, 'end') == 300
    assert c.observed_samples == 200
    assert tuple(f.contact_bits for f in frames) == original


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('length', [11, 15, 20, 100])
def test_long_unknown_invalidates_only_affected_contact(mode, length):
    p = processor(mode)
    frames = [sample(n, [(.2, .38), (1.2, 1.38)] if 100 <= n < 300 else [],
                     [0] if 150 <= n < 150 + length else []) for n in range(420)]
    model, obs = replay(p, frames)
    near, far = [c for c in p.contacts if c.low < 96], [c for c in p.contacts if c.low >= 96]
    assert any(getattr(c, 'exclusion', None) == 'local_unknown_timeout'
               or getattr(c, 'interrupted', None) == 'local_unknown_timeout' for c in near)
    assert len(far) == 1 and time_ms(p, far[0], 'end') == 300
    assert not getattr(far[0], 'interrupted', None)
    # Simultaneous new touches remain ambiguous under the existing identity rules.
    assert not model.audit[0]['recovered']
    assert len(obs) == len(frames)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_ambiguous_foot_change_is_not_joined(mode):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 200 else
                     [(.65, .83)] if 200 <= n < 300 else [], [0] if 197 <= n < 203 else [])
              for n in range(340)]
    model, _ = replay(p, frames)
    assert not model.audit[0]['recovered']
    assert len(p.contacts) == 2
    assert not (p.summary()['valid_steps'])


def test_no_left_or_right_evidence_no_recovery_and_bounded_queue():
    model = GroundObservationModel(DeviceLayout.linear(8))
    obs = []
    for n in range(100):
        obs.extend(model.feed(sample(n, zero_segments=[7])))
        assert len(model._queue) <= 10
    obs.extend(model.flush())
    assert len(obs) == 100 and all(o.unresolved_segments == {7} for o in obs)
    assert not any(event['recovered'] for event in model.audit)


def test_two_module_premise_does_not_arbitrarily_choose_modules():
    model = GroundObservationModel(DeviceLayout.linear(8))
    out = model.feed(sample(0))
    out.extend(model.feed(sample(1, [(.2, .38), (2.2, 2.38), (4.2, 4.38)])))
    out.extend(model.flush())
    assert out[1].unresolved_segments == {0, 2, 4}
    assert all(out[1].frame.valid_bits[96:192])


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_two_nonadjacent_modules_and_cross_seam_are_allowed(mode):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 250 else
                     [(2.92, 3.1)] if 400 <= n < 600 else []) for n in range(640)]
    replay(p, frames)
    assert len(p.contacts) == 2
    assert p.contacts[-1].confirmed
    assert time_ms(p, p.contacts[-1], 'start') == 400


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_clear_endpoints_do_not_create_a_contact(mode):
    p = processor(mode)
    # Under the test premise a short clear-to-clear gap preserves the clear state.
    model, _ = replay(p, [sample(n, zero_segments=[0] if 100 <= n < 104 else []) for n in range(150)])
    assert not p.contacts and p.summary()['valid_steps'] == 0
    assert model.audit[0]['start_sample'] == 100 and model.audit[0]['end_sample'] == 104


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_fractional_edges_flow_into_contact_step_and_support_metrics(mode):
    p = processor(mode)
    frames = []
    for n in range(1200):
        contacts = [(.2, .38)] if 100 <= n < 300 else [(.62, .8)] if 400 <= n < 600 else [(1.2, 1.38)] if 700 <= n < 900 else []
        zero = [0] if 100 <= n < 102 or 300 <= n < 302 or 400 <= n < 402 else []
        frames.append(sample(n, contacts, zero))
    replay(p, frames)
    assert time_ms(p, p.contacts[0], 'start') == 100.5
    assert time_ms(p, p.contacts[0], 'end') == 300.5
    if mode == 'walk':
        assert p.summary()['steps'][0]['time_s'] == pytest.approx(.3)
    else:
        s = p.summary()
        assert s['contacts'][0]['contact_s']['value'] == pytest.approx(.2)
        assert s['steps'][0]['time_s']['value'] == pytest.approx(.3)
        assert s['cycles'][0]['single_support_s']['value'] == pytest.approx(.3995)
        assert s['cycles'][0]['flight_s']['value'] == pytest.approx(.2)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_validated_toe_keeps_first_raw_edge_and_short_wide_contact_stays_a_barrier(mode):
    p = processor(mode)
    frames = []
    for n in range(500):
        contacts = [(.312, .312)] if 100 <= n < 109 else [(.22, .4)] if 109 <= n < 300 else [(.62, .8)] if 400 <= n < 405 else []
        frames.append(sample(n, contacts))
    replay(p, frames)
    assert len(p.contacts) == 2
    assert time_ms(p, p.contacts[0], 'start') == 100
    assert p.contacts[0].confirmed
    assert not p.contacts[1].confirmed
    assert p.summary()['valid_steps'] == 0


def test_fractional_handoff_uses_combined_occupancy_not_independent_corrections():
    p = processor('run')
    frames = [sample(n, [(.2, .38)] if 100 <= n < 300 else [(1.2, 1.38)] if 300 <= n < 500 else
                     [(2.2, 2.38)] if 600 <= n < 800 else [], [0, 1] if 299 <= n < 301 else []) for n in range(840)]
    replay(p, frames)
    s = p.summary()
    assert s['cycles'][0]['single_support_s']['value'] == pytest.approx(.4)
    assert s['cycles'][0]['double_support_s']['value'] == 0
    assert s['cycles'][0]['flight_s']['value'] == pytest.approx(.1)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_session_tail_flush_and_raw_history_remain_complete(qtbot, mode):
    from engine.overground_session import OvergroundSession
    p = processor(mode)
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 320 else [], [0] if n >= 310 else []) for n in range(315)]
    for f in frames:
        session.on_frame(f)
    session.halt()
    report = session.build_report('manual')
    assert tuple(report.export_frames) == tuple(f.contact_bits for f in frames)
    assert len(report.export_timestamps) == len(frames)
    assert not session._frame_filter._queue
    assert session.processor.contacts[0].end is None
    assert 'ground_observation' not in report.report_config_snapshot
    summary = report.walking_summary if mode == 'walk' else report.running_summary
    assert all('edge_estimates' not in c and 'unknown_intervals' not in c for c in summary['contacts'])
    assert session.processor.last_sample == 314


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_known_bad_boundary_only_invalidates_its_module(mode):
    p = processor(mode)
    model = GroundObservationModel(p.device.layout, (40,), .18 if mode == 'walk' else .035)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 300 else []) for n in range(340)]
    # An independent contact beside the unavailable beam cannot erase this foot.
    bits = bytearray(frames[150].contact_bits)
    bits[41] = 1
    bits[125:142] = b'\x01' * 17
    output = []
    for f in frames:
        output.extend(model.feed(replace(f, contact_bits=bytes(bits)) if f.sample_index == 150 else f))
    output.extend(model.flush())
    affected = next(o for o in output if o.frame.sample_index == 150)
    assert affected.unknown_segments == (0,)
    assert not affected.unresolved_segments
    assert all(affected.frame.valid_bits[96:192])


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_repeated_nine_unknown_one_reliable_expires_release_candidate(mode):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 300 else [],
                     [0] if n >= 300 and (n - 300) % 10 != 9 else []) for n in range(440)]
    replay(p, frames)
    c = p.contacts[0]
    assert getattr(c, 'exclusion', None) == 'local_unknown_timeout' or c.interrupted == 'local_unknown_timeout'
    assert p.summary()['valid_steps'] == 0
    assert c.end is None and c.absent_samples < p.config.release_ms


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_repeated_unknown_does_not_extend_touch_confirmation_forever(mode):
    p = processor(mode, confirmation_ms=15)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 300 else [],
                     [0] if 100 <= n < 300 and (n - 100) % 10 != 9 else []) for n in range(340)]
    replay(p, frames)
    assert len(p.contacts) == 1
    assert not p.contacts[0].confirmed
    assert p.contacts[0].observed_samples < 15


def test_known_bad_beam_is_neither_blocked_nor_reliable_clear():
    model = GroundObservationModel(DeviceLayout.linear(8), (576,))
    f = sample(0)
    bits = bytearray(f.contact_bits); bits[576] = 1
    obs = model.feed(replace(f, contact_bits=bytes(bits)))[0]
    assert obs.bits[576] == 0
    assert not obs.reliable(576, 580)
    assert obs.reliable(580, 590)
    assert f.contact_bits[576] == 0


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_unknown_cross_seam_cannot_confirm_false_release(mode):
    p = processor(mode)
    frames = [sample(n, [(.94, 1.08)] if 100 <= n < 300 else []) for n in range(340)]
    for n in range(295, 310):
        valid = bytearray(frames[n].valid_bits); valid[:96] = bytes(96)
        bits = bytearray(frames[n].contact_bits); bits[:96] = bytes(96)
        frames[n] = replace(frames[n], contact_bits=bytes(bits), valid_bits=bytes(valid))
    replay(p, frames)
    c = p.contacts[0]
    assert getattr(c, 'exclusion', None) == 'local_unknown_timeout' or c.interrupted == 'local_unknown_timeout'
    assert c.end is None


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_missing_only_known_bad_region_is_not_clear_evidence(mode):
    p = processor(mode)
    model = GroundObservationModel(p.device.layout, (40,))
    observations = model.feed(sample(0))
    obs = observations[0]
    assert not obs.reliable(40, 40)
    assert obs.reliable(20, 36)


def test_gap_in_sample_counter_never_bridges_a_long_device_interval():
    model = GroundObservationModel(DeviceLayout.linear(8))
    output = model.feed(sample(0))
    output.extend(model.feed(sample(1, zero_segments=[0])))
    output.extend(model.feed(sample(500, [(.2, .38)])))
    output.extend(model.flush())
    assert output[1].unresolved_segments == {0}
    assert not any(e['recovered'] for e in model.audit)
    assert not any(o.edges for o in output)


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('continues', [False, True])
def test_adjacent_unknown_does_not_split_a_foot_rolling_across_seam(mode, continues):
    p = processor(mode)
    frames = []
    for n in range(1140):
        contacts = [(.90, .988)] if 100 <= n < 200 else [(1.0, 1.10)] if continues and 200 <= n < 400 else [(2.2, 2.38)] if 500 <= n < 700 else [(3.2, 3.38)] if 900 <= n < 1100 else []
        frames.append(sample(n, contacts, [1] if 198 <= n < 208 else []))
    replay(p, frames)
    assert len(p.contacts) == 3
    c = p.contacts[0]
    assert time_ms(p, c, 'start') == 100
    assert time_ms(p, c, 'end') == (400 if continues else 203.5)
    assert not getattr(c, 'problem', None) and not getattr(c, 'exclusion', None)
    assert p.summary()['valid_steps'] == 2 and p.summary()['valid_cycles'] == 1
    if mode == 'run':
        cycle = p.summary()['cycles'][0]
        assert cycle['single_support_s']['value'] == pytest.approx(.5 if continues else .3035)
        assert cycle['flight_s']['value'] == pytest.approx(.3 if continues else .4965)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_two_feet_in_nonadjacent_modules_keep_unique_events(mode):
    p = processor(mode)
    frames = []
    for n in range(1040):
        contacts = []
        if 100 <= n < 400:
            contacts.append((.2, .38))
        if 300 <= n < 600:
            contacts.append((2.2, 2.38))
        if 700 <= n < 1000:
            contacts.append((4.2, 4.38))
        frames.append(sample(n, contacts, [0] if 398 <= n < 402 else [6] if n % 6 == 0 else []))
    replay(p, frames)
    assert len(p.contacts) == 3
    assert time_ms(p, p.contacts[0], 'end') == 399.5
    assert time_ms(p, p.contacts[1], 'start') == 300
    assert time_ms(p, p.contacts[1], 'end') == 600
    assert p.summary()['valid_steps'] == 2 and p.summary()['valid_cycles'] == 1


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_known_bad_led_does_not_make_same_module_dark_pulses_unrecoverable(mode):
    p = processor(mode)
    p.device = replace(p.device, bad_indices=(576,))
    frames = [sample(n, [(6.2, 6.38)] if 100 <= n < 300 else [],
                     [6] if n % 6 == 0 else []) for n in range(340)]
    model, _ = replay(p, frames)
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    assert time_ms(p, p.contacts[0], 'start') <= 101
    assert time_ms(p, p.contacts[0], 'end') <= 303
    assert not getattr(p.contacts[0], 'exclusion', None) and not getattr(p.contacts[0], 'interrupted', None)
    assert all(e['recovered'] for e in model.audit if e['segment_index'] == 6 and e['start_sample'] > 0)


def test_short_bad_boundary_pulse_can_clear_but_cannot_supply_a_touch_time():
    for after in ([], [(6.2, 6.38)]):
        model = GroundObservationModel(DeviceLayout.linear(8), (576,))
        out = []
        for n in range(20):
            out.extend(model.feed(sample(n, [(6.010, 6.024)] if 5 <= n < 8 else after if n >= 8 else [])))
        out.extend(model.flush())
        event = next(e for e in model.audit if e['start_sample'] == 5)
        assert event['recovered'] == (not after)


def test_fractional_first_touch_does_not_require_a_prior_departure_for_cycle_flight():
    p = processor('run')
    frames = [sample(n, [(7.12, 7.28)] if 100 <= n < 350 else
                        [(7.42, 7.58)] if 500 <= n < 750 else
                        [(7.72, 7.88)] if 900 <= n < 1150 else [],
                     [7] if 96 <= n < 100 else []) for n in range(1200)]
    replay(p, frames)
    assert p.contacts[0].start == 97.5
    cycle = p.summary()['cycles'][0]
    assert cycle['duration_s']['value'] == .8025
    assert cycle['flight_s']['valid']
    assert cycle['flight_s']['value'] == .3
    assert cycle['single_support_s']['value'] == .5025


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('length', range(1, 11))
def test_lift_after_hidden_cross_seam_continuation_uses_whole_foot_bounds(mode, length):
    p = processor(mode)
    end = 198 + length
    truth = max(200, end - 1)
    frames = [sample(n, [(.90, .988)] if 100 <= n < 200 else
                        [(1.02, 1.20)] if 200 <= n < truth else [],
                     [1] if 198 <= n < end else []) for n in range(250)]
    replay(p, frames)
    c = p.contacts[0]
    assert len(p.contacts) == 1 and c.confirmed
    assert not getattr(c, 'exclusion', None) and not getattr(c, 'interrupted', None)
    if length > 2:
        bounds = [199, end]
        assert c.edge_estimates['lift'] == bounds
        assert bounds[0] < truth <= bounds[1]
        assert time_ms(p, c, 'end') == sum(bounds) / 2
        assert abs(time_ms(p, c, 'end') - truth) <= (bounds[1] - bounds[0]) / 2
    else:
        assert time_ms(p, c, 'end') == 200
    assert p.summary()['duration_s'] == pytest.approx(
        (time_ms(p, c, 'end') - time_ms(p, c, 'start')) / 1000)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_hidden_seam_release_over_ten_unknown_samples_is_not_backfilled(mode):
    p = processor(mode)
    frames = [sample(n, [(.90, .988)] if 100 <= n < 200 else [],
                     [1] if 200 <= n < 212 else []) for n in range(250)]
    replay(p, frames)
    c = p.contacts[0]
    assert c.end is None
    assert p.summary()['duration_s'] is None
    assert getattr(c, 'exclusion', None) == 'local_unknown_timeout' or c.interrupted == 'local_unknown_timeout'


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_unknown_overall_tail_does_not_discard_unrelated_completed_steps(mode):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 300 else
                        [(.62, .8)] if 400 <= n < 600 else
                        [(1.2, 1.38)] if 700 <= n < 900 else [],
                     [7] if 200 <= n < 950 else []) for n in range(980)]
    replay(p, frames)
    summary = p.summary()
    assert len(p.contacts) == 3 and all(c.confirmed and c.end is not None for c in p.contacts)
    assert summary['valid_steps'] == 2 and summary['valid_cycles'] == 1
    assert summary['duration_s'] is None  # A complete unseen remote event cannot be ruled out.


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_later_known_final_edge_restores_overall_duration_after_earlier_loss(mode):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 300 else
                        [(1.2, 1.38)] if 700 <= n < 900 else [],
                     [7] if 200 <= n < 500 else []) for n in range(980)]
    replay(p, frames)
    assert p.summary()['duration_s'] == pytest.approx(.8)


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('seam', [False, True])
def test_two_clear_beams_inside_one_foot_use_existing_four_cm_geometry(mode, seam):
    p = processor(mode)
    low, high, hole = (180, 210, 190) if seam else (110, 135, 120)
    frames = []
    for n in range(450):
        f = sample(n)
        bits = bytearray(f.contact_bits)
        if 100 <= n < 400:
            bits[low:high + 1] = b'\x01' * (high - low + 1)
            if 150 <= n < 350:
                bits[hole:hole + 2] = b'\x00' * 2
        frames.append(replace(f, contact_bits=bytes(bits)))
    replay(p, frames)
    assert len(p.contacts) == 1
    c = p.contacts[0]
    assert c.confirmed and time_ms(p, c, 'start') == 100 and time_ms(p, c, 'end') == 400
    assert not getattr(c, 'exclusion', None) and not getattr(c, 'interrupted', None)
    assert not p.issues


def test_two_feet_with_small_internal_gaps_do_not_violate_two_segment_premise():
    from hardware.ground_observation import classify_ground_frame
    f = sample(0)
    bits = bytearray(f.contact_bits)
    for low, high, hole in ((10, 35, 20), (110, 135, 120)):
        bits[low:high + 1] = b'\x01' * (high - low + 1)
        bits[hole:hole + 2] = b'\x00' * 2
    f = replace(f, contact_bits=bytes(bits))
    assert classify_ground_frame(f).valid_bits == f.valid_bits


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_new_narrow_heel_in_occupied_module_does_not_erase_existing_foot(mode):
    p = processor(mode)
    frames = []
    for n in range(550):
        feet = [(.2, .38)] if 100 <= n < 300 else []
        if 200 <= n < 260:
            feet += [(.624, .624)]
        elif 260 <= n < 500:
            feet += [(.62, .8)]
        frames.append(sample(n, feet))
    replay(p, frames)
    assert len(p.contacts) == 2
    assert [time_ms(p, c, 'start') for c in p.contacts] == [100, 200]
    assert [time_ms(p, c, 'end') for c in p.contacts] == [300, 500]
    assert all(c.confirmed and not getattr(c, 'exclusion', None) and not getattr(c, 'interrupted', None) for c in p.contacts)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_remote_narrow_pulses_do_not_turn_a_real_heel_into_long_missing_data(mode):
    p = processor(mode)
    frames = []
    for n in range(360):
        feet = [(.312, .312)] if 100 <= n < 160 else [(.22, .4)] if 160 <= n < 300 else []
        if 108 <= n < 110:
            feet += [(2.312, 2.312), (4.312, 4.312), (6.312, 6.312)]
        frames.append(sample(n, feet))
    replay(p, frames)
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    assert time_ms(p, p.contacts[0], 'start') == 100
    assert time_ms(p, p.contacts[0], 'end') == 300
    assert not getattr(p.contacts[0], 'exclusion', None) and not getattr(p.contacts[0], 'interrupted', None)


def test_persistent_third_narrow_contact_never_keeps_arbitrary_first_two_modules():
    m = GroundObservationModel(DeviceLayout.linear(8))
    out = []
    for n in range(150):
        feet = [(.2, .38), (2.2, 2.38)] if 20 <= n else []
        if n >= 100:
            feet += [(4.312, 4.312)]
        out.extend(m.feed(sample(n, feet)))
    out.extend(m.flush())
    assert any(o.unresolved_segments >= {0, 2, 4} for o in out if o.frame.sample_index >= 100)
    assert all(not any(o.bits) for o in out if o.frame.sample_index >= 120)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_inner_fragments_uniquely_inside_existing_foot_keep_identity(mode):
    p = processor(mode)
    frames = []
    for n in range(400):
        f = sample(n, [(.2, .42)] if 100 <= n < 300 else [])
        if 180 <= n < 230:
            bits = bytearray(f.contact_bits)
            bits[25:31] = bytes(6)
            f = replace(f, contact_bits=bytes(bits))
        frames.append(f)
    replay(p, frames)
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    assert time_ms(p, p.contacts[0], 'end') == 300
    assert not p.issues


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_remote_narrow_pulse_beside_gap_cannot_erase_existing_foot(mode):
    p = processor(mode)
    frames = []
    for n in range(360):
        contacts = [(.2, .38)] if 100 <= n < 300 else []
        if n in (150, 151, 153):
            contacts += [(2.312, 2.312), (4.312, 4.312), (6.312, 6.312)]
        frames.append(sample(n, contacts, [2, 4, 6] if n == 152 else []))
    replay(p, frames)
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    assert time_ms(p, p.contacts[0], 'start') == 100
    assert time_ms(p, p.contacts[0], 'end') == 300


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_narrow_heel_across_short_loss_keeps_initial_observed_time(mode):
    p = processor(mode)
    frames = [sample(n, [(.312, .312)] if 100 <= n < 160 else
                     [(.22, .4)] if 160 <= n < 300 else [], [0] if 105 <= n < 108 else [])
              for n in range(360)]
    replay(p, frames)
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    assert time_ms(p, p.contacts[0], 'start') == 100
    assert time_ms(p, p.contacts[0], 'end') == 300


def test_inferred_third_module_does_not_invalidate_two_reliably_observed_modules():
    m = GroundObservationModel(DeviceLayout.linear(8))
    out = []
    for n in range(80):
        feet = [(2.2, 2.38)] if 10 <= n < 50 else [(.2, .38), (1.2, 1.38)] if n >= 50 else []
        out.extend(m.feed(sample(n, feet, [2] if 50 <= n < 55 else [])))
    out.extend(m.flush())
    transition = [o for o in out if 50 <= o.frame.sample_index < 55]
    assert any(o.unresolved_segments == {2} for o in transition)
    assert all(all(o.frame.valid_bits[:192]) and any(o.bits[:96]) and any(o.bits[96:192]) for o in transition)


def test_wide_foot_beside_known_bad_beam_does_not_erase_entire_module():
    from hardware.ground_observation import classify_ground_frame
    frame = sample(0, [(5.72, 5.99)])
    observed = classify_ground_frame(frame, (576,))
    assert observed.valid_bits == frame.valid_bits
    assert frame.contact_bits[575] == 1


def test_rolling_heel_to_toe_uses_previous_footprint_for_association():
    p = processor('walk')
    frames = []
    for n in range(650):
        f = sample(n)
        bits = bytearray(f.contact_bits)
        if 100 <= n < 600:
            low = min(34, 5 + max(0, n - 450) // 3)
            high = min(34, low + 19)
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        frames.append(replace(f, contact_bits=bytes(bits)))
    replay(p, frames)
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    assert time_ms(p, p.contacts[0], 'start') == 100
    assert time_ms(p, p.contacts[0], 'end') == 600


def test_known_bad_inside_foot_cannot_grow_narrow_history():
    model = GroundObservationModel(DeviceLayout.linear(8), (576,))
    for n in range(1500):
        model.feed(sample(n, [(5.9, 6.12)] if n >= 100 else []))
        assert len(model._narrow_previous) <= 2
    for n in range(1500, 1525):
        model.feed(sample(n))
    assert not model._narrow_previous
