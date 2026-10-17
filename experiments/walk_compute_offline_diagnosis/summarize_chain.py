"""Full-chain coarse costs, separate from tape-stage costs and live ETW."""
import argparse
import json
from pathlib import Path
from summarize import stats

HERE = Path(__file__).resolve().parent


def main(folder, output):
    assert not output.exists()
    data = json.loads((folder / 'chain.json').read_text())
    stage = json.loads((HERE / 'windows_summary01.json').read_text())
    core = {t['case']: t['contact_core_blocks'] for t in stage['trials']}
    results = []
    for t in data['trials']:
        result = {'case': t['case'], 'phases': {}}
        for phase, selected in [('formal', None), ('contact_core', core[t['case']]),
                                 ('initial_empty', list(range(5))), ('post_contact_empty', list(range(25, 30)))]:
            values = []
            for repeat in t['repeats']:
                assert repeat['report_and_quality_exact']
                rows = [r for r in repeat['blocks'] if r['block'] >= 0 and (selected is None or r['block'] in selected)]
                n = sum(r['raw_last'] - r['raw_first'] + 1 for r in rows)
                values.append({'samples': n, 'cpu_ms': sum(r['thread_cpu_ns'] for r in rows) / 1e6,
                               'wall_ms': sum(r['wall_ns'] for r in rows) / 1e6,
                               'thread_cycles': sum(r['thread_cycles'] for r in rows)})
            result['phases'][phase] = {'repeats': values,
                    'cpu_us_per_input': stats([v['cpu_ms'] * 1000 / v['samples'] for v in values]),
                    'wall_us_per_input': stats([v['wall_ms'] * 1000 / v['samples'] for v in values]),
                    'cycles_per_input': stats([v['thread_cycles'] / v['samples'] for v in values])}
        result['terminal_repeats'] = [r['terminal'] for r in t['repeats']]
        results.append(result)
    output.write_text(json.dumps({'scope': 'Original full synchronous chain, no GUI/USB/SDK or tape wrappers. cycles are not instructions or converted time.', 'trials': results}, ensure_ascii=False, indent=2) + '\n')
    for t in results:
        print(t['case'], t['phases']['contact_core'])


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('folder', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    main(args.folder, args.output)
