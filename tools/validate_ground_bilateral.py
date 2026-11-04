"""Replay exported Windows frames without changing source files or deploying code.

Usage: python -m tools.validate_ground_bilateral INPUT.xlsx ... --output-dir DIR
"""
import argparse
from dataclasses import fields
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from openpyxl import load_workbook

from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.modes.walking_processor import WalkingProcessor
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import masked_frame, uncertain_contact
from hardware.sensor_frame import DeviceLayout, SensorFrame, SensorSegment
from hardware.walking_preflight import PreparedDevice
from reporting.excel import build_report_workbook
from reporting.ground_bilateral import bilateral_html


def validate(path, output):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    book = load_workbook(path, read_only=True, data_only=True)
    snapshot = {key: json.loads(item) for key, item in book['Device and Config'].values}
    if snapshot.get('raw_buffer', {}).get('truncated'):
        raise ValueError('Cannot validate a passage from a truncated frame buffer')
    walking = 'Walking Summary' in book
    cls, processor = (WalkingConfig, WalkingProcessor) if walking else (OvergroundRunningConfig, OvergroundRunningProcessor)
    config = cls(**{key: item for key, item in snapshot.items() if key in {f.name for f in fields(cls) if f.init}})
    device = snapshot['device']
    layout = DeviceLayout(tuple(SensorSegment(**segment) for segment in device['layout']['segments']),
                          tuple(device['layout'].get('invalid_bit_indices', ())))
    prepared = PreparedDevice(layout, device['stream_id'], device['checked_sample_index'], 0,
                              device['healthy_samples'], bad_indices=tuple(device['bad_indices']))
    p = processor(config, prepared)
    optical = GroundStabilityFilter(layout, prepared.bad_indices)
    frames = iter(book['LED Frames'].values)
    assert next(frames) == ('timestamp', 'hex_string')
    first_time = None
    first_sample = prepared.checked_sample_index + 1
    name = 'Walking contacts' if walking else 'Running contacts'
    original_rows = iter(book[name].values)
    columns = next(original_rows)
    origins = []
    for original in original_rows:
        row = dict(zip(columns, original))
        if row.get('touch_sample') is not None:
            touch = json.loads(row['touch_s'])['value'] if walking else row['touch_s.value']
            origins.append(row['touch_sample'] - round(touch * 1000))
    assert origins and len(set(origins)) == 1, 'Original contact records must agree on the export clock origin'
    count = 0
    for timestamp, encoded in frames:
        if first_time is None:
            first_time = timestamp
            assert first_sample == origins[0] + round(first_time * 1000), 'Export clock does not match preparation boundary'
        delta = (timestamp - first_time) * 1000
        assert abs(delta - round(delta)) < 1e-6, 'Export time is not on the device millisecond grid'
        sample = first_sample + round(delta)
        packed = np.frombuffer(bytes.fromhex(encoded), dtype=np.uint8)
        bits = np.unpackbits(packed, bitorder='little')
        assert len(bits) == layout.bit_count
        frame = SensorFrame(device['stream_id'], layout, sample, sample, sample * 1000000,
                            bits.tobytes(), b'\x01' * layout.bit_count, (255 - packed).tobytes())
        for measured in optical.feed(masked_frame(frame, prepared.bad_indices)):
            p.process(measured, masked_contact=uncertain_contact(measured, prepared.bad_indices))
        count += 1
    book.close()
    for measured in optical.flush():
        p.process(measured, masked_contact=uncertain_contact(measured, prepared.bad_indices))
    report = p.build_report('manual')
    summary = report.walking_summary if walking else report.running_summary
    bilateral = summary['bilateral']
    from data.subject_store import SubjectStore
    from reporting.repository import ReportRepository
    with TemporaryDirectory(prefix='ground-bilateral-') as temporary:
        store = SubjectStore(Path(temporary) / 'validation.sqlite3')
        session_id = store.record_session(None, config, report)
        restored = store.get_session(session_id).report
        restored_summary = restored.walking_summary if walking else restored.running_summary
        assert restored_summary['bilateral'] == bilateral
        assert ReportRepository(store).get_package(session_id).payload.bilateral == bilateral
    # Independent lower-level check: integrate 1 ms binary support arrays,
    # rather than calling the interval-boundary implementation again.
    checked = 0
    for source, derived in zip(summary['cycles'], bilateral['records']['cycles']):
        metrics = derived['metrics']
        if not metrics['single_support_s']['valid']:
            continue
        a, z = (next(c for c in summary['contacts'] if c['id'] == source[key]) for key in ('from_id', 'to_id'))
        start, end = a['touch_sample'], z['touch_sample']
        ticks = np.arange(start, end)
        own, other = np.zeros(len(ticks), dtype=bool), np.zeros(len(ticks), dtype=bool)
        for contact in summary['contacts']:
            if contact['touch_sample'] is None or contact['lift_sample'] is None:
                continue
            active = (ticks >= contact['touch_sample']) & (ticks < contact['lift_sample'])
            if contact['label'] == a['label']:
                own |= active
            else:
                other |= active
        assert abs(np.count_nonzero(own & ~other) / 1000 - metrics['single_support_s']['value']) < 1e-8
        assert abs(np.count_nonzero(own & other) / 1000 - metrics['total_double_support_s']['value']) < 1e-8
        checked += 1
    shape_audit = []
    for c in p.contacts:
        if not c.confirmed:
            continue
        start = round(c.start * 1000) if walking else c.start
        end = round(c.end * 1000) if walking and c.end is not None else c.end
        # Saved centre samples are deliberately sparse and are not phase truth.
        evidence = getattr(c, 'position_samples', ()) if walking else getattr(c, 'edges', ())
        shape_audit.append({'contact_id': c.id, 'start_sample': start, 'end_sample': end,
                            'stored_shape_records': len(evidence),
                            'shape_encoding': 'sparse_centre_samples' if walking else 'edge_runs',
                            'phase_truth_available': False})
    stem = path.stem
    output.mkdir(parents=True, exist_ok=True)
    (output / f'{stem}.summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / f'{stem}.html').write_text('<meta charset="utf-8">' + bilateral_html(summary), encoding='utf-8')
    result_book = build_report_workbook(report)
    result_book.save(output / f'{stem}.bilateral.xlsx')
    result_book.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    return {'source': str(path), 'sha256': digest, 'mode': 'walk' if walking else 'run',
            'source_algorithm': snapshot.get('algorithm'), 'starting_foot': config.starting_foot,
            'frames': count, 'valid_touches': summary['valid_touches'],
            'independently_checked_support_cycles': checked,
            'sqlite_and_agent_roundtrip_equal': True,
            'counts': {code: {side: stats[side]['count'] for side in ('left', 'right', 'unknown')}
                       for code, stats in bilateral['statistics'].items()},
            'missing_reasons': {code: stats['all']['missing_reasons'] for code, stats in bilateral['statistics'].items()},
            'shape_evidence': shape_audit,
            'validation_scope': 'software replay and interval arithmetic; no independent anatomical/phase ground truth'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    results = []
    for path in args.inputs:
        result = validate(path, args.output_dir)
        results.append(result)
        print(json.dumps({key: result[key] for key in ('source', 'frames', 'valid_touches', 'independently_checked_support_cycles')}, ensure_ascii=False), flush=True)
    (args.output_dir / 'validation.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
