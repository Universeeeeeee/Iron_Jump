"""Recompute qualification from preserved raw evidence; never records a target."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from check_stable import inspect as stable_check, read, sha, write
from check_changing import inspect as changing_check
from field import protocol
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'native_stack_capture'))
from align_clock import mapping
from external_report import work_bounds, pair_result

HERE = Path(__file__).resolve().parent


def main(args):
    root = HERE.parent.parent
    evidence = args.raw / 'evidence01'
    plans = {name: read(HERE / name) for name in ('stable_plan01.json', 'native_changing_plan01.json', 'perturbation_plan01.json')}
    for plan in plans.values():
        assert all(sha(root / p) == h for p, h in plan['source_sha256'].items())
        assert sha(args.raw / 'ironjump-gil-observer.exe') == plan['observer_sha256']
    stable = read(evidence / 'stable01/run01/result.json')
    for mode in ('held', 'released'):
        folder = evidence / 'stable01/run01'
        rows = [json.loads(line) for line in (folder / mode / 'samples.jsonl').read_text().splitlines()]
        assert stable_check(read(folder / (mode + '_record.json')), rows, plans['stable_plan01.json']) == stable['controls'][mode]
    assert stable['passed']
    folder = evidence / 'native_changing01/run01'
    native = read(folder / 'result.json')
    rows = [json.loads(line) for line in (folder / 'samples.jsonl').read_text().splitlines()]
    assert dict(plan_sha256=sha(HERE / 'native_changing_plan01.json'),
        **changing_check(read(folder / 'record.json'), rows, plans['native_changing_plan01.json'])) == native
    assert native['controlled_changing_oracle_pass']
    failed_folder = args.raw / 'changing_failed01/run01'
    failed = read(failed_folder / 'result.json')
    failed_rows = [json.loads(line) for line in (failed_folder / 'samples.jsonl').read_text().splitlines()]
    failed_plan = read(HERE / 'changing_plan01.json')
    assert not changing_check(read(failed_folder / 'record.json'), failed_rows, failed_plan)['controlled_changing_oracle_pass']
    assert not failed['controlled_changing_oracle_pass']
    with zipfile.ZipFile(evidence / 'changing_sources01.zip') as z:
        assert all(hashlib.sha256(z.read(p)).hexdigest() == h for p, h in failed_plan['source_sha256'].items())
    perturbation = read(evidence / 'perturbation01/run01/result.json')
    plan = plans['perturbation_plan01.json']; pairs = []
    for i, order in enumerate(plan['orders'], 1):
        cases = {}
        for mode in order:
            folder = evidence / 'perturbation01/run01' / f'pair{i}_{mode}'
            record = read(folder / 'record.json'); saved = read(folder / 'analysis.json')
            fixtures = {p: read(folder / 'synthetic' / p / 'progress.json') for p in ('gui', 'sdk')}
            maps = [mapping(record['anchors'])] + [mapping(f['anchors']) for f in fixtures.values()]
            clock = dict(maps[0], host_ns_offset_lower=max(m['host_ns_offset_lower'] for m in maps),
                         host_ns_offset_upper=min(m['host_ns_offset_upper'] for m in maps))
            assert clock == saved['clock']
            for role, fixture in fixtures.items():
                for before, after in zip(record['before'], record['after']):
                    if before['pid'] != fixture['pid']:
                        continue
                    row = saved['processes'][role]['threads'][before['name']]
                    assert row['work'] == work_bounds(fixture['history'], before['name'], before, after, clock)
                    assert row['cpu_s'] == (after['user_100ns'] + after['kernel_100ns'] - before['user_100ns'] - before['kernel_100ns']) / 1e7
                    assert row['cycles'] == after['cycles'] - before['cycles']
                    assert before['creation_100ns'] == after['creation_100ns'] and before['active'] and after['active']
            if mode == 'on':
                rows = [json.loads(line) for line in (folder / 'samples.jsonl').read_text().splitlines()]
                assert protocol(rows, fixtures['gui']['pid'], plan['count'])
            cases[mode] = saved
        pairs.append(dict(pair=i, **pair_result(cases['off'], cases['on'], plan['pair_limits'])))
    assert pairs == perturbation['pairs'] and perturbation['synthetic_perturbation_pass'] and all(p['passed'] for p in pairs)
    old_acceptance = [root / 'experiments/native_stack_capture/field_reviews' / name / 'acceptance.json' for name in
        ('20261017_field_wait01/round02', '20261017_field_cpu01/round01')]
    assert all(not read(p)['measurement_acceptance_pass'] for p in old_acceptance)
    result = dict(stable_raw_recomputed=True, native_oracle_raw_recomputed=True,
        failed_python_marker_preserved_and_still_failed=True, failed_source_snapshot_verified=True,
        all_three_synthetic_pairs_recomputed=True, original_native_acceptance_unchanged_false=True,
        actual_load_disturbance_pass=False, field_GIL_holder_identified=False, root_cause_or_fix_complete=False,
        raw_archive_sha256=sha(args.raw / 'evidence01.zip'),
        plans_sha256={name: sha(HERE / name) for name in plans},
        original_acceptance_sha256={str(p.relative_to(root)): sha(p) for p in old_acceptance})
    write(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--raw', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    main(p.parse_args())
