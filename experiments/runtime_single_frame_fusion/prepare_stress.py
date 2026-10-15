"""Build labelled continuous synthetic loads from recorded bits and recorded JPEGs."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'exports/ground_boundary_latency_20261014/field_run_20261015_02'


def build(seconds):
    folder = HERE / 'stress_sources' / str(seconds)
    folder.mkdir(parents=True, exist_ok=False)
    meta = json.loads((SOURCE / 'report.json').read_text(encoding='utf-8'))['report_config_snapshot']
    checked = meta['device']['checked_sample_index']
    start = checked - 3500
    total = 3501 + seconds * 1000
    prefix = np.arange(start, 108609)
    loop = np.arange(104000, 108609)
    mapping = np.concatenate((prefix, np.tile(loop, (total + len(loop) - 1) // len(loop))))[:total]
    with np.load(SOURCE / 'raw_frames.npz') as source:
        assert np.array_equal(source['sample_indices'], np.arange(len(source['sample_indices'])))
        usable = np.ones(source['bits'].shape[1], dtype=np.bool_)
        usable[meta['device']['bad_indices']] = False
        assert np.array_equal(source['bits'][108608], source['bits'][104000]), 'Raw seam states differ'
        assert not np.any(source['bits'][108608][usable]), 'Loop seam must be clear on usable beams'
        origin_ns = int(source['received_ns'][start])
        samples = np.arange(start, start + total, dtype=np.int64)
        np.savez_compressed(folder / 'raw_frames.npz', bits=source['bits'][mapping], wire=source['wire'][mapping],
                            sample_indices=samples, frame_indices=samples,
                            received_ns=origin_ns + np.arange(total, dtype=np.int64) * 1000000)
    (folder / 'report.json').write_text(json.dumps({'report_config_snapshot': meta}), encoding='utf-8')
    (folder / 'timing.json').write_text(json.dumps({'rows': [{'touch_sample': int(samples[-1]) - 1200}]}))
    original_start = json.loads((SOURCE / 'camera_record_start.json').read_text())['host_ns']
    offset = (origin_ns - original_start) / 1e9
    with (SOURCE / 'camera.csv').open(newline='') as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        rows = [r for r in reader if offset <= float(r['record_elapsed_seconds']) < offset + 14.4]
    selected, last = [], -1.0
    for row in rows:
        elapsed = float(row['record_elapsed_seconds'])
        if elapsed - last >= 1 / 30:
            selected.append(row)
            last = elapsed
    rows = selected
    assert len(rows) > 100
    with (folder / 'camera.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for i in range(int(np.ceil(total / 1000 * 30))):
            row = dict(rows[i % len(rows)])
            row.update(record_elapsed_seconds=str(i / 30), capture_frame_index=str(i), sample_time=str(i / 30))
            writer.writerow(row)
    os.link(SOURCE / 'camera.mjpg', folder / 'camera.mjpg')
    (folder / 'camera_record_start.json').write_text(json.dumps({'host_ns': origin_ns}))
    (folder / 'construction.json').write_text(json.dumps({
        'label': 'synthetic continuous pressure input; not additional human trials or synchronized pose ground truth',
        'formal_seconds': seconds, 'frames': total, 'checked_sample': checked,
        'prefix_source_range_inclusive': [start, 108608], 'loop_source_range_inclusive': [104000, 108608],
        'sample_clock': 'continuous 1000Hz, no resets at seams', 'host_cadence': 'synthetic uniform 1ms',
        'camera': 'recorded JPEG offsets repeated independently at 30fps; synthetic timing and frame identities',
        'mapping_sha256': hashlib.sha256(mapping.tobytes()).hexdigest(),
        'raw_input_sha256': hashlib.sha256((folder / 'raw_frames.npz').read_bytes()).hexdigest()}, indent=2))
    print('Built continuous pressure source', seconds, total, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('seconds', type=int, choices=(60, 300))
    args = parser.parse_args()
    replay = (HERE / 'fixed_replay.py').read_text(encoding='utf-8')
    assert replay.count('QTimer.singleShot(45000,timeout)') == 1
    replay = replay.replace('QTimer.singleShot(45000,timeout)', 'QTimer.singleShot((args.seconds+60)*1000,timeout)')
    (HERE / 'stress_replay.py').write_text(replay, encoding='utf-8')
    probe = (HERE / 'gui_probe.py').read_text(encoding='utf-8')
    probe = probe.replace("runpy.run_path(str(HERE/'fixed_replay.py')", "runpy.run_path(str(HERE/'stress_replay.py')")
    probe = probe.replace("'fixed_geometry_cache.py']", "'fixed_geometry_cache.py', 'stress_gui_probe.py', 'stress_replay.py']")
    (HERE / 'stress_gui_probe.py').write_text(probe, encoding='utf-8')
    build(args.seconds)
