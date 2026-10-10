"""Offline raw spatial observation beside the unchanged 10 ms measurement path.

Inputs are matched_usb.npz and the same test's metadata.json. This tool never
opens a device or chooses which path is physically correct. JSONL retains every
sample, including reliable clear bits and unavailable beams, for later review.
"""
import argparse
from collections import Counter
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.modes.walking_processor import WalkingProcessor
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import masked_frame, uncertain_contact
from hardware.sensor_frame import DeviceLayout, SensorSegment, SensorFrame
from hardware.walking_preflight import PreparedDevice


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_wire(payload, layout):
    # Deliberately independent of DeviceLayout.contact_bits / parser LUTs.
    decoded = []
    for segment in layout.segments:
        part = payload[segment.wire_index * 12:(segment.wire_index + 1) * 12]
        bits = [1 - ((int(byte) >> bit) & 1) for byte in part for bit in range(8)]
        decoded.extend(bits[::-1] if segment.reversed else bits)
    return bytes(decoded)


def raw_groups(bits, positions):
    groups = []
    for i, blocked in enumerate(bits):
        if not blocked:
            continue
        if groups and positions[i] - positions[groups[-1][1]] <= .04:
            groups[-1][1] = i
        else:
            groups.append([i, i])
    return groups


def contact_evidence(processor, mode):
    scale = 1000 if mode == 'walk' else 1
    return [{'id': c.id, 'epoch': c.epoch, 'first_sample': round(c.start * scale),
             'last_sample': round(c.last * scale),
             'end_sample': c.end * scale if c.end is not None else None,
             'low': c.low, 'high': c.high, 'confirmed': c.confirmed,
             'touch_known': c.touch_known,
             'position_known': getattr(c, 'position_known', None),
             'side': c.side, 'outcome': c.candidate_outcome,
             'reason': getattr(c, 'exclusion', None) or getattr(c, 'problem', None)
                       or getattr(c, 'interrupted', None)} for c in processor.active]


def compare_contacts(raw, filtered, mode):
    """Optical temporal-overlap candidates; IDs are local, never zipped as truth."""
    scale = 1000 if mode == 'walk' else 1
    rows = []
    for c in filtered.contacts:
        if not c.confirmed:
            continue
        matches = [r for r in raw.contacts if r.confirmed
                   and r.start < (c.end or c.last + 1 / scale)
                   and (r.end or r.last + 1 / scale) > c.start
                   and abs(raw.positions[r.low] - filtered.positions[c.low]) <= .45]
        rows.append({'filtered_id': c.id, 'raw_candidate_ids': [r.id for r in matches],
                     'association': 'unique_optical_overlap' if len(matches) == 1 else 'unresolved',
                     'filtered_first_sample': round(c.start * scale),
                     'raw_first_samples': [round(r.start * scale) for r in matches],
                     'first_sample_delta': round((matches[0].start - c.start) * scale)
                         if len(matches) == 1 else None,
                     'physical_identity_validated': False})
    return rows


def pending_evidence(processor, mode):
    scale = 1000 if mode == 'walk' else 1
    return [{'first_sample': round(p['start'] * scale),
             'last_sample': round(p['last'] * scale), 'low': p['low'], 'high': p['high'],
             'observed_samples': p['samples'], 'outcome': 'pending',
             'isolated_clear_evidence': p.get('isolated_clear', False)}
            for p in processor._narrow_candidates]


def compare(input_dir, output_dir, mode):
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = [input_dir / 'matched_usb.npz', input_dir / 'metadata.json']
    outputs = [output_dir / name for name in ('frames.jsonl', 'comparison.json',
                                             'raw_summary.json', 'filtered_summary.json')]
    if {p.resolve() for p in inputs} & {p.resolve() for p in outputs}:
        raise ValueError('Output must not overwrite a source')
    hashes = {str(p.resolve()): digest(p) for p in inputs}
    root = Path(__file__).resolve().parents[1]
    source_paths = [Path(__file__), *[root / p for p in (
        'engine/modes/walking_processor.py', 'engine/modes/overground_running_processor.py',
        'hardware/beam_filter.py', 'engine/overground_session.py')]]
    source_hashes = {str(p.resolve()): digest(p) for p in source_paths}
    meta = json.loads(inputs[1].read_text(encoding='utf-8'))
    dev = meta['device']
    geometry = dev['layout']
    layout = DeviceLayout(tuple(SensorSegment(**s) for s in geometry['segments']),
                          tuple(geometry['invalid_bit_indices']))
    bad = tuple(dev['bad_indices'])
    device = PreparedDevice(layout, dev['stream_id'], dev['checked_sample_index'],
                            dev['checked_monotonic_ns'], dev['healthy_samples'], bad_indices=bad)
    config_class, factory = ((WalkingConfig, WalkingProcessor) if mode == 'walk'
                             else (OvergroundRunningConfig, OvergroundRunningProcessor))
    keys = {f.name for f in fields(config_class) if f.init}
    config = config_class(**{k: v for k, v in meta.items() if k in keys})
    raw, filtered = factory(config, device), factory(config, device)
    optical = GroundStabilityFilter(layout, bad)
    changed, clear_removed, blocked_removed, delays, runtimes, raw_runtimes = [], 0, 0, [], [], []
    delivered = []
    with np.load(inputs[0]) as data, outputs[0].open('w', encoding='utf-8') as handle:
        counters, bits, wire, arrivals = (data[k] for k in ('frame_indices', 'bits', 'wire', 'received_ns'))
        indices = data['sample_indices'] if 'sample_indices' in data else counters
        if (bits.shape != (len(indices), layout.bit_count)
                or wire.shape != (len(indices), layout.payload_bytes)
                or len(arrivals) != len(indices) or len(counters) != len(indices) or not len(indices)):
            raise ValueError('Capture arrays and layout do not agree')
        if not np.all((bits == 0) | (bits == 1)):
            raise ValueError('Contact bits must be binary')
        valid = bytearray(b'\x01' * layout.bit_count)
        for index in layout.invalid_bit_indices:
            valid[index] = 0
        unavailable = sorted(set(bad) | set(layout.invalid_bit_indices))
        available = np.ones(layout.bit_count, dtype=bool)
        available[unavailable] = False
        by_sample = {int(n): i for i, n in enumerate(indices)}
        if len(by_sample) != len(indices) or np.any(np.diff(indices) <= 0):
            raise ValueError('Counter reset/duplicate requires a separate capture stream')
        if not np.array_equal(np.diff(indices), np.diff(counters)):
            raise ValueError('Device/sample clock deltas disagree; correct the stream origin mapping')

        def consume(measured, fed_sample):
            nonlocal clear_removed, blocked_removed
            started = time.perf_counter_ns()
            filtered.process(measured, masked_contact=uncertain_contact(measured, bad))
            runtimes.append((time.perf_counter_ns() - started) / 1e6)
            delivered.append(measured.sample_index)
            delays.append(fed_sample - measured.sample_index)
            offset = by_sample[measured.sample_index]
            source = bits[offset].copy()
            source[list(unavailable)] = 0
            value = np.frombuffer(measured.contact_bits, dtype=np.uint8)
            delta = np.flatnonzero(available & (source != value))
            if len(delta):
                changed.append({'sample': measured.sample_index, 'beam_indices': delta.tolist()})
                clear_removed += int(np.count_nonzero(available & (source == 0) & (value == 1)))
                blocked_removed += int(np.count_nonzero(available & (source == 1) & (value == 0)))

        for i, (n, counter, b, w, arrival) in enumerate(zip(indices, counters, bits, wire, arrivals)):
            n = int(n)
            if decode_wire(w, layout) != b.tobytes():
                raise ValueError(f'Wire/bit mismatch at device sample {n}')
            frame = SensorFrame(device.stream_id, layout, int(counter), n, int(arrival),
                                b.tobytes(), bytes(valid), w.tobytes(),
                                dropped_frames_before=max(0, n - int(indices[i-1]) - 1) if i else 0)
            clean = masked_frame(frame, bad)
            started = time.perf_counter_ns()
            raw.process(clean, masked_contact=uncertain_contact(clean, bad))
            raw_ms = (time.perf_counter_ns() - started) / 1e6
            raw_runtimes.append(raw_ms)
            handle.write(json.dumps({'sample': n, 'device_frame_index': frame.frame_index,
                                     'raw_contact_bytes_hex': frame.contact_bits.hex(),
                                     'wire_hex': frame.wire_payload.hex(), 'valid_bytes_hex': frame.valid_bits.hex(),
                                     'received_monotonic_ns': frame.received_monotonic_ns,
                                     'dropped_frames_before': frame.dropped_frames_before,
                                     'quality_flags': list(frame.quality_flags),
                                     'unavailable_beams': unavailable,
                                     'raw_groups': raw_groups(frame.contact_bits, layout.positions_m),
                                     'available_spatial_groups': raw_groups(masked_frame(frame, unavailable).contact_bits, layout.positions_m),
                                     'owners': contact_evidence(raw, mode),
                                     'pending_candidates': pending_evidence(raw, mode),
                                     'finished_reason': raw.finished_reason, 'processor_ms': raw_ms},
                                    ensure_ascii=False) + '\n')
            for measured in optical.feed(clean):
                consume(measured, n)
        for measured in optical.flush():
            consume(measured, int(indices[-1]))
        assert delivered == indices.tolist(), 'Filter changed sample count/order'
        evidence = {'frame_count': len(indices), 'first_sample': int(indices[0]),
                    'last_sample': int(indices[-1]), 'counter_gap_count': int(np.count_nonzero(np.diff(indices) != 1)),
                    'device_counter_gap_count': int(np.count_nonzero(np.diff(counters) != 1)),
                    'first_device_frame_index': int(counters[0]), 'last_device_frame_index': int(counters[-1]),
                    'sample_indices_source': 'sample_indices' if 'sample_indices' in data else 'legacy_frame_indices',
                    'wire_decodes_identically': True, 'known_unavailable_beams': unavailable,
                    'input_frame_deletion_count': 0, 'shadow_bit_rewrite_count': 0,
                    'filter_changed_frames': len(changed), 'filter_changed_bits': changed,
                    'healthy_clear_bits_filled': clear_removed, 'healthy_blocked_bits_removed': blocked_removed,
                    'filter_delivery_delay_samples': dict(Counter(delays)),
                    'filtered_cpu_ms_p50_p95_max': np.percentile(runtimes, [50, 95, 100]).tolist(),
                    'raw_cpu_ms_p50_p95_max': np.percentile(raw_runtimes, [50, 95, 100]).tolist(),
                    'valid_bits_source': 'layout_snapshot_only; NPZ omits runtime validity and quality flags',
                    'live_acquisition_backlog_verified': False, 'packet_crc_verified_by_this_tool': False}
    summaries = [raw.summary(), filtered.summary()]
    for path, summary in zip(outputs[2:], summaries):
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    assert hashes == {str(p.resolve()): digest(p) for p in inputs}, 'Source changed during replay'
    assert source_hashes == {str(p.resolve()): digest(p) for p in source_paths}, 'Code changed during replay'
    evidence.update(mode=mode, input_hashes=hashes, code_hashes=source_hashes,
                    input_unchanged=True, physical_truth_verified=False,
                    production_filter_replacement_approved=False,
                    contact_overlap_review=compare_contacts(raw, filtered, mode))
    outputs[1].write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_dir', type=Path)
    parser.add_argument('--mode', choices=('walk', 'run'), required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.input_dir, args.output_dir, args.mode)
    print(json.dumps({k: result[k] for k in ('mode', 'frame_count', 'filter_changed_frames',
                     'healthy_clear_bits_filled', 'healthy_blocked_bits_removed', 'input_unchanged')}, indent=2))


if __name__ == '__main__':
    main()
