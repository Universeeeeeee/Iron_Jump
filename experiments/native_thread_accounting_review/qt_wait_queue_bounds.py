"""Conservative prefix-lag bounds around old paired waits; no interpolation."""
import hashlib
import json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def bounds(producers, host_begin, host_end):
    assert host_begin <= host_end
    left, right = [], []
    for source, rows in producers.items():
        assert all(a[0] < b[0] for a,b in zip(rows, rows[1:]))
        for i, row in enumerate(rows):
            # snapshot timestamps precede the actual reads. Only the next call
            # by this same producer bounds completion of the prior read.
            if i+1 < len(rows) and rows[i+1][0] <= host_begin:
                left.append(dict(source=source, index=i, row=row, read_end_upper_ns=rows[i+1][0]))
            if row[0] >= host_end:
                right.append(dict(source=source, index=i, row=row))
    if not left or not right: return dict(available=False)
    a = max(left, key=lambda v:v['row'][5])
    b = min(right, key=lambda v:v['row'][1])
    assert a['row'][1] <= b['row'][1] and a['row'][5] <= b['row'][5]
    return dict(available=True, before=a, after=b,
        completed_sample_prefix_bounds=[a['row'][1], b['row'][1]],
        received_sample_prefix_bounds=[a['row'][5], b['row'][5]],
        unfinished_batch_prefix_lag_lower_bound=max(0, a['row'][5]-b['row'][1]),
        meaning='Received sample prefix minus completed-batch prefix; may include work already processed inside an unfinished batch. Not exact deque pending or per-frame progress.')


if __name__ == '__main__':
    summary_path = HERE/'qt_label_wait_summary01.json'; summary = read(summary_path)
    assert all(sha(ROOT/n) == v for n,v in summary['bindings'].items())
    original = ROOT/'experiments/native_stack_capture/field_reviews/20261017_field_wait01/round02/batch_wait_witnesses01.json'
    witness = read(original)
    assert all(sha(ROOT/n) == v for n,v in witness['inputs_sha256'].items())
    path = ROOT/'experiments/single_usb_human_etw/runs/20261017_214905_5c874d97_walk_off/capture/measurement.json'
    m = read(path); assert m['pid'] == summary['pid'] == 17752
    assert m['threads'] == dict(gui=20420, consumer=5376)
    probe = ROOT/'experiments/single_usb_human_etw/queue_probe.py'
    frozen = probe.parent/'frozen_sources.json'
    assert sha(frozen) == m['frozen_sources_sha256']
    assert sha(probe) == read(frozen)['files'][str(probe.relative_to(ROOT))]
    raw = path.parent/'raw_frames.npz'
    with np.load(raw) as z:
        assert np.all(np.diff(z['sample_indices']) == 1)
        assert np.all(np.diff(z['frame_indices']) == 1)
        assert np.all(z['dropped_frames_before'] == 0)
    producers = dict(common=m['queue_common'], samples=m['queue_samples'])
    ordered = sorted(producers['common']+producers['samples']+[m['queue_final']], key=lambda r:r[0])
    for a,b in zip(ordered, ordered[1:]):
        assert a[1] <= b[1] and a[5] <= b[5]
    assert all(r[7] == r[5]-r[1] and r[8] == r[7]-r[3] and r[7] >= r[3] >= 0 for r in ordered)
    mapping = witness['mapping']; assert 10**9 % mapping['qpc_frequency'] == 0
    factor = 10**9//mapping['qpc_frequency']; results = []
    for pair in summary['guarded_simultaneous_waits']:
        lo, hi = pair['qpc_bounds']
        a = lo*factor+mapping['host_ns_offset_lower']
        b = hi*factor+mapping['host_ns_offset_upper']
        results.append(dict(pair=pair, full_host_ns_envelope=[a,b], **bounds(producers,a,b)))
    result = dict(pid=17752, mapping=mapping, pairs=results,
        all_pairs=len(results), pairs_with_lag_lower_bound_over_100=sum(v.get('unfinished_batch_prefix_lag_lower_bound',0)>100 for v in results),
        limits=['Bounds use monotone prefix counters and complete prior-read brackets, not nearest-point interpolation.',
            'An unfinished batch can include already processed frames; do not call this exact deque occupancy or name an exact active 20-frame batch.',
            'These are workload associations for qualitative paired waits, not GIL attribution, wait duration, CPU percentages or observer qualification.',
            'The six original pending snapshots remain separate; none became a direct GUI-latch point.'],
        bindings={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__), summary_path, original, path, probe, frozen, raw)},
        primary_root_identified=False, field_fix_verified=False, old_acceptance_upgraded=False)
    with (HERE/'qt_wait_queue_bounds01.json').open('x') as f: json.dump(result, f, indent=2)
    print(json.dumps(dict(all_pairs=result['all_pairs'], associated_over_100=result['pairs_with_lag_lower_bound_over_100'],
        minimum_lower_bound=min(v['unfinished_batch_prefix_lag_lower_bound'] for v in results if v['available'])),indent=2))
