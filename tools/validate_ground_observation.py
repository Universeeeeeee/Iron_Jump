"""Offline comparison and known-time erasure sweep for ground measurements.

python -m tools.validate_ground_observation --capture CAPTURE.csv --bad-bit 576
CSV accepts complete raw_packet_hex rows or unfiltered raw_hex USB blocks.
stable10 is the production 10 ms filter; local and sweep retain the legacy model.
--output saves JSON; --windows-dir saves one-second review windows around each
unknown run. All inputs are read-only. No device access or host-clock filtering.
"""
import argparse
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.modes.walking_processor import WalkingProcessor
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from hardware.beam_filter import BeamDisplayFilter, GroundStabilityFilter
from hardware.beam_quality import masked_frame
from hardware.ground_observation import GroundObservationModel
from hardware.protocol import E_DATA_REPORT, protocol_parser
from hardware.sensor_frame import DeviceLayout, SensorFrame, SensorFrameAssembler
from hardware.walking_preflight import PreparedDevice


def load_capture(path, chunk_size=None):
    parser_buffer, assembler, frames = bytearray(), SensorFrameAssembler(), []
    protocol_errors = []
    with open(path, encoding='utf-8-sig', newline='') as source:
        for row in csv.DictReader(source):
            raw = bytes.fromhex(row.get('raw_packet_hex') or row['raw_hex'])
            received = int(row.get('usb_received_monotonic_ns') or row['monotonic_ns'])
            size = chunk_size or len(raw)
            for offset in range(0, len(raw), size):
                parser_buffer.extend(raw[offset:offset + size])
                while True:
                    ret, kind, _, packet, _ = protocol_parser(parser_buffer, on_error=protocol_errors.append)
                    if ret:
                        break
                    if kind == E_DATA_REPORT:
                        frame = assembler.feed(packet, received)
                        if frame is not None:
                            frames.append(frame)
                    issues = assembler.pop_issues()
                    if issues:
                        raise ValueError(f'Acquisition issues: {issues}')
    if protocol_errors:
        raise ValueError(f'Protocol validation errors: {protocol_errors[:10]}')
    if parser_buffer:
        raise ValueError('Incomplete final packet')
    return frames


def make_processor(mode, layout, stream, bad=()):
    factory, config = ((WalkingProcessor, WalkingConfig) if mode == 'walk' else
                       (OvergroundRunningProcessor, OvergroundRunningConfig))
    return factory(config(stop_type='Software command'), PreparedDevice(layout, stream, -1, 0, 1000, bad_indices=tuple(bad)))


def compare(frames, mode, method, bad):
    p = make_processor(mode, frames[0].layout, frames[0].stream_id, bad)
    model = GroundObservationModel(p.device.layout, bad, .18 if mode == 'walk' else .035)
    display = BeamDisplayFilter(10)
    stable = GroundStabilityFilter(p.device.layout, bad)
    start = time.perf_counter()
    for raw in frames:
        frame = masked_frame(raw, bad)
        if method == 'local':
            for obs in model.feed(frame):
                p.process(obs.frame, obs)
        elif method == 'stable10':
            for filtered in stable.feed(frame):
                p.process(filtered)
        elif method == 'display10':
            payload = display.feed(raw)
            filtered = masked_frame(replace(raw, contact_bits=raw.layout.contact_bits(payload), wire_payload=payload), bad)
            p.process(filtered)
        else:
            p.process(frame)
    if method == 'local':
        for obs in model.flush():
            p.process(obs.frame, obs)
    if method == 'stable10':
        for filtered in stable.flush():
            p.process(filtered)
    elapsed = time.perf_counter() - start
    s = p.summary()
    result = {'seconds': elapsed, 'frames_per_second': len(frames) / elapsed,
              'confirmed_contacts': sum(c.confirmed for c in p.contacts),
              'valid_steps': s['valid_steps'], 'valid_cycles': s['valid_cycles'],
              'issues': len(p.issues), 'summary': s}
    if method == 'local':
        result['observation_model'] = model.snapshot()
    return result


def sweep():
    layout = DeviceLayout.linear(3)
    valid = b'\x01' * layout.bit_count
    contact = bytes(int(.2 <= x <= .38) for x in layout.positions_m)
    max_error = 0
    cases = 0
    for mode in ('walk', 'run'):
        for length in range(1, 11):
            for boundary in (100, 300):
                for offset in range(-length, 2):
                    start = boundary + offset
                    p = make_processor(mode, layout, 'sweep')
                    model = GroundObservationModel(layout, match_margin_m=.18 if mode == 'walk' else .035)
                    for n in range(340):
                        bits = contact if 100 <= n < 300 else bytes(layout.bit_count)
                        if start <= n < start + length:
                            bits = b'\x01' * 96 + bits[96:]
                        frame = SensorFrame('sweep', layout, n, n, n + 1, bits, valid, b'')
                        for obs in model.feed(frame):
                            p.process(obs.frame, obs)
                    for obs in model.flush():
                        p.process(obs.frame, obs)
                    assert len(p.contacts) == 1 and p.contacts[0].confirmed
                    c = p.contacts[0]
                    assert c.end is not None
                    estimate = (c.start if boundary == 100 else c.end) * (1000 if mode == 'walk' else 1)
                    error = abs(estimate - boundary)
                    name = 'touch' if boundary == 100 else 'lift'
                    bounds = c.edge_estimates.get(name)
                    if bounds is not None:
                        assert bounds[0] < boundary <= bounds[1], (mode, start, length, bounds, boundary)
                        assert error <= (bounds[1] - bounds[0]) / 2 + 1e-9
                    else:
                        assert error == 0
                    assert error <= (length + 1) / 2 + 1e-9
                    max_error = max(max_error, error)
                    cases += 1
    max_duration_error = 0
    duration_cases = 0
    # Independent continuous truth; ten erased samples enclose an 11ms interval.
    # Touch just after a reliable old sample tests the near-worst two-edge error.
    true_touch, true_lift = 99.000001, 300
    for mode in ('walk', 'run'):
        for touch_length in range(1, 11):
            for lift_length in range(1, 11):
                p = make_processor(mode, layout, 'duration')
                model = GroundObservationModel(layout, match_margin_m=.18 if mode == 'walk' else .035)
                for n in range(340):
                    bits = contact if true_touch <= n < true_lift else bytes(layout.bit_count)
                    if 100 <= n < 100 + touch_length or 300 - lift_length <= n < 300:
                        bits = b'\x01' * 96 + bits[96:]
                    f = SensorFrame('duration', layout, n, n, n + 1, bits, valid, b'')
                    for obs in model.feed(f):
                        p.process(obs.frame, obs)
                for obs in model.flush():
                    p.process(obs.frame, obs)
                assert len(p.contacts) == 1 and p.contacts[0].confirmed
                c = p.contacts[0]
                assert c.end is not None
                for name, truth in [('touch', true_touch), ('lift', true_lift)]:
                    bounds = c.edge_estimates[name]
                    assert bounds[0] < truth <= bounds[1]
                    value = (c.start if name == 'touch' else c.end) * (1000 if mode == 'walk' else 1)
                    assert abs(value - truth) <= (bounds[1] - bounds[0]) / 2 + 1e-9
                measured = (c.end - c.start) * (1000 if mode == 'walk' else 1)
                error = abs(measured - (true_lift - true_touch))
                assert error <= (touch_length + lift_length + 2) / 2 + 1e-9
                max_duration_error = max(max_duration_error, error)
                duration_cases += 1
    return {'cases': cases, 'duration_cases': duration_cases,
            'recoverable_contact_retention': 1.0, 'edge_bound_contains_truth': True,
            'max_contact_duration_error_ms': max_duration_error, 'max_edge_error_ms': max_error,
            'truth': 'synthetic optical contact [100,300) with known erasure positions'}


def review_windows(directory, frames, audit):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Overlapping ±1s windows are merged to keep frequent-noise exports bounded.
    ranges = []
    for event in sorted(audit, key=lambda e: e['start_sample']):
        start, end = event['start_sample'] - 1000, event['end_sample'] + 1000
        if ranges and start <= ranges[-1][1]:
            ranges[-1][1] = max(end, ranges[-1][1])
        else:
            ranges.append([start, end])
    for i, (start, end) in enumerate(ranges):
        with open(directory / f'window_{i + 1}.csv', 'w', newline='', encoding='utf-8-sig') as target:
            writer = csv.writer(target)
            writer.writerow(['frame_index', 'sample_index', 'device_time_s', 'led_payload_hex'])
            for frame in frames:
                if start <= frame.sample_index < end:
                    writer.writerow([frame.frame_index, frame.sample_index, frame.sample_time_s, frame.wire_payload.hex(' ')])


def overlay(frames, centre):
    """Known contacts OR recorded clear-field noise; truth is not live motion."""
    result = []
    trajectory = [(100, 350, centre), (500, 750, centre + .3), (900, 1150, centre + .6)]
    for f in frames[:1500]:
        bits = bytearray(f.contact_bits)
        for start, end, x in trajectory:
            if start <= f.sample_index < end:
                for i, pos in enumerate(f.layout.positions_m):
                    if x - .08 <= pos <= x + .08:
                        bits[i] = 1
        payload = bytes(sum((not bits[i + j]) << j for j in range(8))
                        for i in range(0, len(bits), 8))
        result.append(replace(f, contact_bits=bytes(bits), wire_payload=payload))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='append', default=[])
    parser.add_argument('--bad-bit', type=int, action='append', default=[])
    parser.add_argument('--output')
    parser.add_argument('--windows-dir')
    parser.add_argument('--skip-sweep', action='store_true')
    parser.add_argument('--empty-field', action='store_true', help='Assert declared empty-field truth and synthetic overlay retention')
    args = parser.parse_args()
    result = {'sweep': None if args.skip_sweep else sweep(), 'captures': []}
    for capture in args.capture:
        frames = load_capture(capture)
        if not frames:
            raise ValueError('No complete frames')
        digest = lambda fs: hashlib.sha256(b''.join(f.wire_payload for f in fs)).hexdigest()
        before = digest(frames)
        # Independent parser boundaries: split every recorded USB block into 7 bytes.
        fragmented = load_capture(capture, 7)
        assert [(f.frame_index, f.sample_index, f.wire_payload) for f in frames] == [
            (f.frame_index, f.sample_index, f.wire_payload) for f in fragmented]
        assert digest(fragmented) == before
        entry = {'path': str(Path(capture).resolve()), 'frames': len(frames),
                 'wire_payload_sha256': before, 'seven_byte_parse_identical': True, 'modes': {}}
        for mode in ('walk', 'run'):
            entry['modes'][mode] = {method: compare(frames, mode, method, args.bad_bit)
                                    for method in ('raw', 'display10', 'stable10', 'local')}
        for mode in ('walk', 'run'):
            for method in ('stable10', 'local'):
                fragmented_result = compare(fragmented, mode, method, args.bad_bit)
                assert fragmented_result['summary'] == entry['modes'][mode][method]['summary']
        entry['seven_byte_measurement_identical'] = True
        if args.empty_field:
            for mode in ('walk', 'run'):
                for method in ('stable10', 'local'):
                    assert entry['modes'][mode][method]['confirmed_contacts'] == 0
                    assert entry['modes'][mode][method]['valid_steps'] == 0
        if args.empty_field and len(frames) >= 1500 and len(frames[0].layout.segments) >= 2:
            entry['synthetic_overlay'] = {}
            centres = [.3, len(frames[0].layout.segments) - .8]
            centres.extend(s + .2 for s in sorted({i // 96 for i in args.bad_bit})
                           if s + .88 < len(frames[0].layout.segments))
            for centre in dict.fromkeys(centres):
                noise = overlay(frames, centre)
                entry['synthetic_overlay'][str(centre)] = {
                    mode: {method: compare(noise, mode, method, args.bad_bit)
                           for method in ('raw', 'display10', 'stable10', 'local')} for mode in ('walk', 'run')}
                for mode in ('walk', 'run'):
                    for method in ('stable10', 'local'):
                        r = entry['synthetic_overlay'][str(centre)][mode][method]
                        assert r['confirmed_contacts'] == 3 and r['valid_steps'] == 2 and r['valid_cycles'] == 1
                        if mode == 'run':
                            cycle = r['summary']['cycles'][0]
                            assert all(cycle[key]['valid'] for key in (
                                'duration_s', 'contact_s', 'swing_s', 'flight_s',
                                'single_support_s', 'double_support_s')), cycle

        assert digest(frames) == before
        if args.windows_dir:
            review_windows(Path(args.windows_dir) / Path(capture).stem, frames,
                           entry['modes']['walk']['local']['observation_model']['intervals'])
        result['captures'].append(entry)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding='utf-8')
    print(json.dumps({'sweep': result['sweep'], 'captures': [
        {'path': c['path'], 'frames': c['frames'], 'modes': {mode: {
            method: {k: r[k] for k in ('frames_per_second', 'confirmed_contacts', 'valid_steps', 'issues')}
            for method, r in methods.items()} for mode, methods in c['modes'].items()}}
        for c in result['captures']]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
