"""Offline power-history review. Never imported by a capture or production path."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
REVIEWS = ROOT / 'experiments/native_stack_capture/field_reviews'
RUNS = ROOT / 'experiments/single_usb_human_etw/runs'
CASES = [
    ('20261017_213018_48007d13_walk_off', 32048, 38724, 'OFF; external observer missed'),
    ('20261017_214905_5c874d97_walk_off', 27535, 33871, 'CSwitch wait stacks'),
    ('20261017_220528_012bb590_walk_off', 29955, 36025, '100 Hz CPU stacks'),
]


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def summary(values):
    return dict(zip(('min', 'p50', 'p95', 'max'),
                    map(float, np.percentile(values, [0, 50, 95, 100]))))


def compare():
    hashes, trials = {}, []
    for case, first, last, profile in CASES:
        folder = RUNS / case / 'capture'
        paths = [folder / name for name in
                 ('measurement.json', 'state.json', 'raw_frames.npz')]
        paths += [REVIEWS / case / 'review01.json']
        if case == CASES[0][0]:
            paths += [REVIEWS / case / 'operator_disturbance_supplement01.json']
        for path in paths:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes[str(path.relative_to(ROOT))] = digest
            if path.parent == folder:
                manifest = read(folder.parent / 'original_manifest.json')
                assert digest == manifest['capture\\' + path.name]['sha256']
        m, state, review = read(paths[0]), read(paths[1]), read(paths[3])
        with np.load(paths[2]) as z:
            samples, frames, receipts = (z[k].copy() for k in
                                        ('sample_indices', 'frame_indices', 'received_ns'))
            bits, dropped = z['bits'].copy(), z['dropped_frames_before'].copy()
        assert np.all(np.diff(samples) == 1) and np.all(np.diff(frames) == 1)
        assert np.all(np.diff(receipts) >= 0) and np.all(dropped == 0)
        assert state['quality']['preflight']['bad_indices'] == [576]
        # A local analysis mask excludes unknown576; it never changes retained data.
        bits[:, 576] = 0
        lo, hi = np.searchsorted(samples, [first, last])
        assert samples[lo] == first and samples[hi] == last
        s, t, b = samples[lo:hi + 1], receipts[lo:hi + 1], bits[lo:hi + 1]
        residual_ms = ((t - t[0]) - (s - s[0]) * 1_000_000) / 1e6
        counts = np.count_nonzero(b, axis=1)
        if case == CASES[0][0]:
            bounded = read(paths[4])['undisturbed_walk_evidence']
            latency = bounded['footprint_receipt_to_paint_ms']
            completion = bounded['consumer_completion_bounds_formal_s']
        else:
            bounded = review.get('main_raw_contact_interval', review.get('main_raw_contact'))
            latency = review['footprint_receipt_to_paint_ms']
            completion = bounded['consumer_completion_bounds_formal_s']
        # Recheck prior summaries against the saved raw timing and batch witnesses.
        points = sorted(m['queue_common'] + [m['queue_final']], key=lambda r: r[0])
        upper = next(r[0] for r in points if r[1] >= last)
        lower = max(r[0] for r in points if r[0] < upper and r[1] < last)
        assert np.allclose([(lower - m['armed_ns']) / 1e9,
                            (upper - m['armed_ns']) / 1e9], completion[-1],
                           rtol=0, atol=1e-9)
        delays = [(m['paints'][str(row['contact_id'])] - int(receipts[
            np.searchsorted(samples, row['sample'])])) / 1e6
                  for row in review['footprint_timings']]
        assert len(delays) == latency['count'] == 11
        assert np.allclose([np.percentile(delays, 95), max(delays)],
                           [latency['p95'], latency['max']], rtol=0, atol=1e-6)
        trials.append({
            'case': case, 'native_profile': profile, 'pid': m['pid'],
            'frozen_sources_sha256': m['frozen_sources_sha256'],
            'archive_first_frame_and_sample': [int(frames[0]), int(samples[0])],
            'outward_samples_inclusive': [first, last],
            'nominal_counter_span_s': (last - first) / 1000,
            'host_receipt_span_s': float((t[-1] - t[0]) / 1e9),
            'receipt_minus_nominal_span_ms': float(residual_ms[-1]),
            'receipt_residual_relative_to_first_ms': summary(residual_ms),
            'successive_receipt_gap_ms': summary(np.diff(t) / 1e6),
            'usable_blocked_beams_per_sample': summary(counts),
            'usable_active_sample_fraction': float(np.mean(counts > 0)),
            'usable_bit_transitions': int(np.count_nonzero(b[1:] != b[:-1])),
            'receipt_to_paint_ms': latency,
            'last_input_receipt_to_batch_completion_bounds_ms': [
                (bound - (int(t[-1]) - m['armed_ns']) / 1e9) * 1000
                for bound in completion[-1]],
        })
    assert len({t['frozen_sources_sha256'] for t in trials}) == 1
    return {'input_sha256': hashes, 'trials': trials,
            'method_limits': [
                '1000Hz is the nominal frame-counter cadence, not an independently synchronized device clock.',
                'Receipt timestamps follow Python USB reading and assembly; residuals include reader scheduling and nominal clock drift. Constant upstream age is invisible.',
                'Raw beam counts/transitions are input geometry descriptors, not Processor cost or physical-contact/step counts.',
                'Completion bounds use prior queue_common/queue_final evidence; independent queue_samples do not establish completion bounds.',
                'First trial excludes kicked segment8 tail. Original failed protocol, traces and calibration decisions are preserved.',
                'No causal comparison of tracing overhead, power duration, temperature or GIL percentages is valid from these three unmatched trials.'
            ]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    output = parser.parse_args().output
    result = compare()
    with output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps(result['trials'], indent=2))
