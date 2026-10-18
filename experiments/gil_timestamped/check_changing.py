"""Oracle-bracketed changing-owner checks; ambiguous transition samples stay unknown."""
import argparse
import bisect
import json
import mmap
from pathlib import Path
import struct
import subprocess
import sys
import time

from check_stable import anchor, read, sha, wait_file, write

HERE = Path(__file__).resolve().parent


def inspect(record, rows, plan):
    a = record['anchors']; f = a[0]['frequency']
    assert f > 0 and all(p['frequency'] == f for p in a)
    lower = max(p['before_ns'] - (p['qpc'] * 10**9 + f - 1) // f for p in a)
    upper = min(p['after_ns'] - p['qpc'] * 10**9 // f for p in a)
    samples = [r for r in rows if r['kind'] == 'sample']
    oracle = [r for r in record['oracle'] if r[2] % 2 == 0 and r[2] == r[6]]
    starts, ends = [r[0] for r in oracle], [r[1] for r in oracle]
    joins, unknown, failures, brackets = [], [], [], []
    ordered = rows[0]['kind'] == 'init' and rows[0]['schema'] == 1 and rows[0]['error'] is None \
        and rows[0]['pid'] == record['ready']['pid'] and rows[0]['qpc_frequency'] == f
    previous = rows[0]['qpc_end']
    for i, sample in enumerate(samples):
        begin, end = sample['qpc_begin'], sample['qpc_end']
        ordered &= sample['ordinal'] == i and previous <= begin <= end \
            and sample['pid'] == record['ready']['pid']
        previous = end
        b = [begin * 10**9 // f + lower, (end * 10**9 + f - 1) // f + upper]
        brackets.append(b)
        before, after = bisect.bisect_right(ends, b[0]) - 1, bisect.bisect_left(starts, b[1])
        if before < 0 or after >= len(oracle):
            unknown.append(dict(ordinal=i, reason='no full oracle bracket')); continue
        p, q = oracle[before], oracle[after]
        if p[2] != q[2] or p[3] not in (1, 2) or p[3:5] != q[3:5]:
            unknown.append(dict(ordinal=i, reason='phase transition or idle')); continue
        expected = record['ready']['tids'][str(p[3])]
        traces = sample['traces']
        owners = [t for t in traces if t.get('owns_gil') is True]
        match = len(owners) == 1 and owners[0].get('os_thread_id') == expected == p[4] \
            and owners[0].get('pid') == record['ready']['pid'] \
            and any(v['name'] == ('hold_a' if p[3] == 1 else 'hold_b') for v in owners[0]['frames'])
        row = dict(ordinal=i, phase=p[3], oracle_epoch=p[2], expected_TID=expected,
                   bracket_ns=b, oracle_before=p, oracle_after=q, matches=match)
        joins.append(row)
        if not match:
            failures.append(row)
    counts = {str(p): sum(j['phase'] == p for j in joins) for p in (1, 2)}
    checks = dict(ordered=ordered and previous <= rows[-1].get('qpc', 0),
        complete=rows[-1]['kind'] == 'complete' and rows[-1]['pid'] == record['ready']['pid']
            and rows[-1]['samples_written'] == len(samples) == plan['count'],
        no_error_rows=len(rows) == len(samples) + 2,
        clock_mapping=0 <= upper - lower <= plan['clock_uncertainty_ns_max'],
        monotone_oracle=all(p[2] <= q[2] and p[5] <= q[5] for p, q in zip(oracle, oracle[1:])),
        same_epoch_consistent=all(p[2] != q[2] or p[3:5] == q[3:5] for p, q in zip(oracle, oracle[1:])),
        held_oracle_heartbeat_still=all(p[2] != q[2] or p[3] == 0 or p[5] == q[5]
                                      for p, q in zip(oracle, oracle[1:])),
        all_read_windows_bounded=all(record['external_bracket_ns'][0] <= b[0] <= b[1]
            <= record['external_bracket_ns'][1] and record['begin']['host_ns'] + plan['phase_margin_ns'] < b[0]
            < b[1] < record['complete']['host_ns'] - plan['phase_margin_ns'] for b in brackets),
        independent_coverage=len(joins) >= plan['eligible_floor'] and all(n >= plan['per_holder_floor'] for n in counts.values()),
        every_eligible_sample_matches=not failures,
        target_recovered=record['complete']['completed'] and record['complete']['pid'] == record['ready']['pid'] \
            and record['complete']['host_ns'] > record['external_bracket_ns'][1],
        clean_exit=record['target_returncode'] == record['observer_returncode'] == 0 and not record['stderr']
            and not record.get('errors') and not record.get('forced_cleanup'))
    return dict(checks=checks, controlled_changing_oracle_pass=all(checks.values()),
        eligible_counts=counts, joins=joins, unknown=unknown, failures=failures,
        scope='Only independently bracketed stable oracle epochs amid changing owners/frames. Transition samples remain unknown, not evidence of correctness or time shares.',
        actual_load_disturbance_pass=False, field_attribution_ready=False)


def main(args):
    args.output.mkdir(exist_ok=False)
    lock = args.output.parent / 'active.lock'; lock.mkdir()
    plan = read(args.plan)
    assert sha(args.tool) == plan['observer_sha256']
    assert all(sha(HERE.parent.parent / p) == h for p, h in plan['source_sha256'].items())
    assert sha(Path(sys.base_prefix) / 'python311.dll') == plan['python_dll_sha256']
    fixture = HERE / plan.get('fixture', 'changing_fixture.py')
    extra = []
    if plan.get('oracle_dll_sha256'):
        assert args.oracle_dll is not None and sha(args.oracle_dll) == plan['oracle_dll_sha256']
        extra = [str(args.oracle_dll)]
    target = observer = None
    record = dict(errors=[], forced_cleanup=[])
    folder = args.output / 'target'
    with (args.output / 'target.log').open('xb') as log, (args.output / 'observer.log').open('xb') as observer_log:
        try:
            target = subprocess.Popen([sys.executable, str(fixture), str(folder), *extra], stdout=log, stderr=subprocess.STDOUT)
            record['ready'] = wait_file(folder / 'ready.json', target)
            assert record['ready']['pid'] == target.pid and target.poll() is None
            (folder / 'go').touch(exist_ok=False)
            record['begin'] = wait_file(folder / 'phase_begin.json', target)
            time.sleep(.5)
            record['anchors'] = [anchor()]
            record['oracle'] = []
            with (folder / 'oracle.bin').open('rb') as backing:
                shared = mmap.mmap(backing.fileno(), 32, access=mmap.ACCESS_READ)
                try:
                    start = time.perf_counter_ns()
                    observer = subprocess.Popen([str(args.tool), str(target.pid), str(plan['count']), str(plan['period_ms']), str(args.output / 'samples.jsonl')], stdout=observer_log, stderr=subprocess.STDOUT)
                    while observer.poll() is None:
                        if time.perf_counter_ns() - start > 5 * 10**9:
                            raise TimeoutError('Changing observer exceeded its declared window')
                        before = time.perf_counter_ns()
                        epoch, phase, owner, heartbeat = struct.unpack_from('<QQQQ', shared)
                        confirm = struct.unpack_from('<Q', shared)[0]
                        after = time.perf_counter_ns()
                        record['oracle'].append([before, after, epoch, phase, owner, heartbeat, confirm])
                        time.sleep(.001)
                    record['external_bracket_ns'] = [start, time.perf_counter_ns()]
                finally:
                    shared.close()
            record['anchors'].append(anchor())
            record['observer_returncode'] = observer.returncode
            record['target_returncode'] = target.wait(timeout=10)
            record['complete'] = read(folder / 'complete.json')
        except BaseException as exc:
            record['errors'].append(repr(exc))
        finally:
            for name, child in (('observer', observer), ('target', target)):
                if child is not None and child.poll() is None:
                    record['forced_cleanup'].append(name)
                    try:
                        child.terminate(); child.wait(timeout=10)
                    except BaseException as exc:
                        record['errors'].append(name + ' cleanup: ' + repr(exc))
    record['stderr'] = (args.output / 'observer.log').read_text(errors='replace')
    write(args.output / 'record.json', record)
    try:
        assert not record['errors'] and not record['forced_cleanup']
        rows = [json.loads(line) for line in (args.output / 'samples.jsonl').read_text().splitlines()]
        result = inspect(record, rows, plan)
        assert sha(args.tool) == plan['observer_sha256']
        assert all(sha(HERE.parent.parent / p) == h for p, h in plan['source_sha256'].items())
        if extra:
            assert sha(args.oracle_dll) == plan['oracle_dll_sha256']
    except BaseException as exc:
        result = dict(controlled_changing_oracle_pass=False, errors=[repr(exc)], record_errors=record['errors'])
    write(args.output / 'result.json', dict(plan_sha256=sha(args.plan), **result))
    if result['controlled_changing_oracle_pass']:
        lock.rmdir()
    print({k: v for k, v in result.items() if k not in ('joins', 'unknown')}, flush=True)
    return 0 if result['controlled_changing_oracle_pass'] else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--tool', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--plan', type=Path, default=HERE / 'changing_plan01.json')
    p.add_argument('--oracle-dll', type=Path)
    raise SystemExit(main(p.parse_args()))
