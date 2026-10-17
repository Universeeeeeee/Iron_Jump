"""Read retained schedule exports; do not start a workload or change capture gates."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
DT = np.dtype([('qpc', '<i8'), ('cpu', '<u2'), ('opcode', 'u1'), ('version', 'u1'),
               ('header_tid', '<u4'), ('header_pid', '<u4'), ('payload', 'u1', 24),
               ('length', '<u2'), ('flags', '<u2')])


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(data, factor, start, end, roles):
    rows = []
    for cpu in np.unique(data['cpu']):
        events = data[data['cpu'] == cpu]
        ids = np.ascontiguousarray(events['payload']).view('<u4').reshape(-1, 6)
        assert np.all(ids[:-1, 0] == ids[1:, 1]), 'Broken CPU switch chain'
        times = events['qpc'] * factor
        assert np.all(np.diff(times) >= 0)
        assert times[0] <= start < end <= times[-1], 'Uncovered window'
        duration = np.maximum(0, np.minimum(times[1:], end) - np.maximum(times[:-1], start))
        assert int(duration.sum()) == end - start
        tids = ids[:-1, 0]
        idle = int(duration[tids == 0].sum())
        rows.append({'cpu': int(cpu), 'idle_seconds': idle / 1e9,
                     'nonidle_residency_fraction': 1 - idle / (end - start),
                     'target_residency_seconds': {
                         role: int(duration[tids == item['tid']].sum()) / 1e9
                         for role, item in roles.items()}})
    seconds = (end - start) / 1e9
    return {'duration_s': seconds, 'logical_processors': rows,
            'mean_nonidle_residency_fraction': float(np.mean([
                r['nonidle_residency_fraction'] for r in rows])),
            'target_residency_seconds': {role: sum(
                r['target_residency_seconds'][role] for r in rows) for role in roles}}


def main():
    previous = ROOT / 'experiments/walk_etw_offline_diagnosis'
    validation = read(previous / 'validation_manifest.json')
    diagnosis = read(previous / 'results02/diagnosis.json')
    alignment_path = ROOT / 'experiments/walk_compute_offline_diagnosis/aligned03.json'
    aligned = {r['case']: r for r in read(alignment_path)['trials']}
    results = []
    for trial in diagnosis['ON_trials']:
        name = trial['case']
        folder = previous / 'evidence' / name
        expected = next(v['files'] for v in validation['evidence'] if v['case'] == name)
        hashes = {n: sha(folder / n) for n in ('schedule.bin', 'metadata.json')}
        assert all(hashes[n] == expected[n]['sha256'] for n in hashes)
        meta = read(folder / 'metadata.json')
        assert meta['binary_sha256'] == hashes['schedule.bin']
        assert all(meta[k] == 0 for k in ('header_events_lost', 'buffers_lost', 'consumer_events_lost'))
        assert 1000000000 % meta['qpc_frequency'] == 0
        factor = 1000000000 // meta['qpc_frequency']
        assert factor == trial['clock_validation']['raw_to_perf_ns_factor']
        data = np.fromfile(folder / 'schedule.bin', dtype=DT)
        cs = data[data['opcode'] == 36]
        assert len(cs) == trial['decode_checks']['CSwitch']
        assert np.all(cs['version'] == 5) and np.all(cs['length'] == 28)
        runs = aligned[name]['runs']
        assert len(runs) == 1
        a, b = runs[0]['start_bounds_ns'], runs[0]['end_bounds_ns']
        windows = {label: summarize(cs, factor, start, end, trial['roles'])
                   for label, start, end in [('outer', a[0], b[1]), ('inner', a[1], b[0])]}
        results.append({'case': name, 'input_sha256': hashes, 'windows': windows})
    output = {'source_sha256': sha(Path(__file__)), 'alignment_sha256': sha(alignment_path),
              'trials': results,
              'scope': 'Original filtered-contact completion brackets. Nonidle scheduled residency is not execution CPU or a frequency measurement. Idle TID=0 intervals can include ISR/DPC; no physical-core/SMT mapping is assumed. Historical clock/lifecycle validation is reused only with matching source hashes. No new capture or threshold changes.'}
    with Path(__file__).with_name('results01.json').open('x', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
