"""Describe the preserved raw contact geometry; no algorithm replay or new capture."""
import argparse
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def analyze():
    prior = HERE.parent / 'single_usb_human_etw'
    block = json.loads((prior / 'walking_block01_review.json').read_text())
    result = []
    for trial in block['trials']:
        capture = prior / 'runs' / trial['case'] / 'capture'
        m = json.loads((capture / 'measurement.json').read_text())
        a = json.loads((capture / 'analysis.json').read_text())
        with np.load(capture / 'raw_frames.npz') as z:
            receipts, samples = z['received_ns'], z['sample_indices']
            formal = (receipts >= m['armed_ns']) & (receipts < m['stop_request_ns'])
            origin = samples[np.flatnonzero(formal)[0]]
            seconds = (samples - origin) // 1000
            dense = [r['device_second'] for r in a['device_contact_bins'] if r['phase'] == 'dense']
            mask = formal & np.isin(seconds, dense)
            bits = z['bits'][mask].copy()
        bits[:, a['bad_indices']] = 0
        active = bits.sum(axis=1)
        runs = bits[:, 0].astype(np.int64) + ((bits[:, 1:] != 0) & (bits[:, :-1] == 0)).sum(axis=1)
        result.append({'case': trial['case'], 'dense_device_seconds': dense, 'dense_frames': int(mask.sum()),
                       'contact_fraction': float((active > 0).mean()), 'mean_active_beams': float(active.mean()),
                       'max_active_beams': int(active.max()), 'mean_contiguous_active_runs': float(runs.mean()),
                       'max_contiguous_active_runs': int(runs.max()),
                       'pattern_change_fraction': float(np.any(bits[1:] != bits[:-1], axis=1).mean()),
                       'unique_bit_patterns': len(np.unique(np.packbits(bits, axis=1), axis=0)),
                       'scope': 'Raw geometry after original bad mask only. Not a processor cost model, same-input claim or new acceptance metric.'})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert not args.output.exists()
    args.output.write_text(json.dumps(analyze(), indent=2) + '\n')
