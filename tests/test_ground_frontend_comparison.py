"""Independent evidence checks for the offline frontend comparison entry."""
from dataclasses import asdict
import json
import numpy as np
import pytest
from hardware.sensor_frame import DeviceLayout, SensorSegment
from tools.compare_ground_frontends import compare, decode_wire


def capture(folder, layout=None):
    layout = layout or DeviceLayout.linear(3)
    n = 450
    bits = np.zeros((n, layout.bit_count), dtype=np.uint8)
    bits[100:300, 85:106] = 1
    bits[200:400, 181:202] = 1  # two feet, three physical modules
    bits[240, 85:106] = 0       # reliable clear must remain in raw evidence
    bits[120, 250] = 1         # isolated distant pulse
    bits[:, 270] = 1           # known unavailable, not healthy clear
    wire = np.zeros((n, layout.payload_bytes), dtype=np.uint8)
    for segment in layout.segments:
        physical = bits[:, layout.segments.index(segment) * 96:(layout.segments.index(segment) + 1) * 96]
        if segment.reversed:
            physical = physical[:, ::-1]
        wire[:, segment.wire_index * 12:(segment.wire_index + 1) * 12] = np.packbits(1 - physical, axis=1, bitorder='little')
    folder.mkdir()
    np.savez(folder / 'matched_usb.npz', frame_indices=np.arange(n), bits=bits, wire=wire, received_ns=np.arange(n)*1000000)
    meta = {'min_contact_time': 60, 'stop_type': 'Software command', 'starting_foot': 'Left',
            'device': {'layout': asdict(layout), 'stream_id': 'test', 'checked_sample_index': -1,
                       'checked_monotonic_ns': 0, 'healthy_samples': 3000, 'bad_indices': [270]}}
    (folder / 'metadata.json').write_text(json.dumps(meta))
    return bits


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_comparison_retains_raw_clear_unavailable_and_all_samples(tmp_path, mode):
    source, output = tmp_path / 'input', tmp_path / 'output'
    bits = capture(source)
    result = compare(source, output, mode)
    assert result['frame_count'] == 450 and result['input_unchanged']
    assert result['healthy_clear_bits_filled'] >= 21
    assert result['known_unavailable_beams'] == [270]
    assert not result['physical_truth_verified'] and not result['production_filter_replacement_approved']
    rows = [json.loads(line) for line in (output / 'frames.jsonl').read_text().splitlines()]
    assert [r['sample'] for r in rows] == list(range(450))
    assert all(bytes.fromhex(r['raw_contact_bytes_hex']) == b.tobytes() for r, b in zip(rows, bits))
    assert not any(bytes.fromhex(rows[240]['raw_contact_bytes_hex'])[85:106])
    assert rows[240]['unavailable_beams'] == [270] and bits[240, 270] == 1


def test_independent_decode_respects_wire_order_reverse_and_calibration(tmp_path):
    layout = DeviceLayout((SensorSegment('1', 2, .2, .0101, True),
                           SensorSegment('2', 0, 1.2, .0101),
                           SensorSegment('3', 1, 2.2, .0101, True)))
    source = tmp_path / 'input'
    bits = capture(source, layout)
    with np.load(source / 'matched_usb.npz') as data:
        assert all(decode_wire(w, layout) == b.tobytes() for w, b in zip(data['wire'], bits))
    result = compare(source, tmp_path / 'output', 'walk')
    assert result['wire_decodes_identically'] and not result['counter_gap_count']


def test_wire_mismatch_is_rejected_instead_of_trusting_archived_bits(tmp_path):
    source = tmp_path / 'input'
    capture(source)
    with np.load(source / 'matched_usb.npz') as data:
        arrays = {k: data[k].copy() for k in data.files}
    arrays['wire'][120, 0] ^= 1
    np.savez(source / 'matched_usb.npz', **arrays)
    with pytest.raises(ValueError, match='Wire/bit mismatch at device sample 120'):
        compare(source, tmp_path / 'output', 'walk')


def test_unavailable_blocked_bits_are_never_counted_as_healthy_filled_clear(tmp_path):
    source = tmp_path / 'input'
    capture(source, DeviceLayout(DeviceLayout.linear(3).segments, (270,)))
    path = source / 'metadata.json'
    meta = json.loads(path.read_text()); meta['device']['bad_indices'] = []
    path.write_text(json.dumps(meta))
    result = compare(source, tmp_path / 'output', 'walk')
    assert result['healthy_clear_bits_filled'] == 0
    assert result['healthy_blocked_bits_removed'] == 0
    assert not result['filter_changed_frames']


def test_missing_counter_samples_are_retained_as_a_gap(tmp_path):
    source = tmp_path / 'input'
    capture(source)
    with np.load(source / 'matched_usb.npz') as data:
        arrays = {k: np.delete(data[k], np.arange(120, 125), axis=0) for k in data.files}
    np.savez(source / 'matched_usb.npz', **arrays)
    output = tmp_path / 'output'
    result = compare(source, output, 'walk')
    rows = [json.loads(line) for line in (output / 'frames.jsonl').read_text().splitlines()]
    assert result['frame_count'] == 445 and result['counter_gap_count'] == 1
    assert rows[120]['sample'] == 125 and rows[120]['dropped_frames_before'] == 5
    assert rows[120]['received_monotonic_ns'] == 125000000


def test_device_counter_and_stream_sample_clock_are_not_conflated(tmp_path):
    source = tmp_path / 'input'
    capture(source)
    with np.load(source / 'matched_usb.npz') as data:
        arrays = {k: data[k].copy() for k in data.files}
    arrays['sample_indices'] = arrays['frame_indices'].copy()
    arrays['frame_indices'] += 10000
    np.savez(source / 'matched_usb.npz', **arrays)
    output = tmp_path / 'output'
    result = compare(source, output, 'walk')
    assert result['first_sample'] == 0 and result['first_device_frame_index'] == 10000
    row = json.loads((output / 'frames.jsonl').read_text().splitlines()[100])
    assert row['sample'] == 100 and row['device_frame_index'] == 10100


def test_compressed_sample_clock_cannot_hide_a_device_counter_gap(tmp_path):
    source = tmp_path / 'input'
    capture(source)
    with np.load(source / 'matched_usb.npz') as data:
        arrays = {k: data[k].copy() for k in data.files}
    arrays['sample_indices'] = arrays['frame_indices'].copy()
    arrays['frame_indices'][120:] += 5
    np.savez(source / 'matched_usb.npz', **arrays)
    with pytest.raises(ValueError, match='clock deltas disagree'):
        compare(source, tmp_path / 'output', 'walk')
