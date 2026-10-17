"""Coarse-block cost comparisons, with no live CPU/GIL interpretation."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def stats(values):
    return {'median': float(np.median(values)), 'min': float(min(values)), 'max': float(max(values))}


def main(folder, output):
    assert not output.exists()
    source = json.loads((folder / 'compute.json').read_text())
    results = []
    for t in source['trials']:
        mapping = np.load(folder / (t['case'] + '_output_map.npy'))
        block = (mapping[:, 0] - t['formal_start']) // 1000
        counts = Counter(map(int, block))
        core = [int(b) for b in np.unique(block) if counts[b] == 1000 and np.all(mapping[block == b, 2] > 0)]
        empty = [b for b in range(5) if counts[b] == 1000 and np.all(mapping[block == b, 2] == 0)]
        # Diagnostic partitions of actual processed contact, not new trial gates.
        subsets = {'formal': None, 'contact_core': core, 'initial_empty': empty,
                   'post_contact_empty_25_29': list(range(25, 30))}
        result = {'case': t['case'], 'strict_oracle_equal': t['strict_oracle_equal'], 'report_sha256': t['report_sha256'],
                  'contact_core_blocks': core, 'stages': {}, 'state_at_core_end': [], 'final_state': t['final_state']}
        for stage in ('quality', 'filter', 'processor'):
            result['stages'][stage] = {}
            for phase, indices in subsets.items():
                repeats = []
                for r in t['repeats']:
                    rows = [row for row in r['stages'][stage] if row['block'] >= 0 and (indices is None or row['block'] in indices)]
                    repeats.append({'cpu_ms': sum(row['thread_cpu_ns'] for row in rows) / 1e6,
                                    'wall_ms': sum(row['wall_ns'] for row in rows) / 1e6,
                                    'blocks': len(rows)})
                n = t['formal_end'] - t['formal_start'] if indices is None else len(indices) * 1000
                result['stages'][stage][phase] = {'samples': n, 'repeats': repeats,
                        'cumulative_cpu_ms': stats([r['cpu_ms'] for r in repeats]),
                        'wall_us_per_raw_input': stats([r['wall_ms'] * 1000 / n for r in repeats]),
                        'cpu_us_per_raw_input': stats([r['cpu_ms'] * 1000 / n for r in repeats])}
        for s in t['states']:
            b = (s['raw_sample'] - t['formal_start']) // 1000
            if b in core:
                result['state_at_core_end'].append(s)
        results.append(result)
    output.write_text(json.dumps({'source_compute_sha256_note': 'See compute.json and input/source manifests; no measured field discarded.',
                                 'core_definition': 'Full 1000-outer-input block with exactly 1000 processor outputs, all containing usable filtered contact. Includes periodic summary in processor scope. No final flush/report in core.',
                                 'trials': results}, ensure_ascii=False, indent=2) + '\n')
    for t in results:
        print(t['case'], 'core', t['contact_core_blocks'])
        for stage, values in t['stages'].items():
            print(stage, 'formal CPU ms', values['formal']['cumulative_cpu_ms'], 'core CPU us/input', values['contact_core']['cpu_us_per_raw_input'], 'core wall', values['contact_core']['wall_us_per_raw_input'])


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('folder', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    main(a.folder, a.output)
