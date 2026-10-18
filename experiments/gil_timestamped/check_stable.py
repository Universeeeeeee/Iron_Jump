"""Synthetic timestamp and owner checks. Never launches a field process."""
import argparse
import ctypes as C
import json
import mmap
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PEER = HERE.parent / 'gil_owner_preflight'
sys.path.insert(0, str(PEER))
from check import read, sha, thread_state, wait_file, write
from dump_check import inspect as inspect_owner


def anchor():
    k = C.WinDLL('kernel32', use_last_error=True)
    q, f = C.c_int64(), C.c_int64()
    assert k.QueryPerformanceFrequency(C.byref(f)) and f.value > 0
    before = time.perf_counter_ns()
    assert k.QueryPerformanceCounter(C.byref(q))
    after = time.perf_counter_ns()
    return dict(before_ns=before, after_ns=after, qpc=q.value, frequency=f.value)


def inspect(record, rows, plan):
    anchors = record['anchors']
    frequency = anchors[0]['frequency']
    assert frequency > 0 and all(a['frequency'] == frequency for a in anchors)
    # Outward integer rounding; keep all clock uncertainty, no midpoint mapping.
    lower = max(a['before_ns'] - (a['qpc'] * 10**9 + frequency - 1) // frequency for a in anchors)
    upper = min(a['after_ns'] - a['qpc'] * 10**9 // frequency for a in anchors)
    samples = [r for r in rows if r['kind'] == 'sample']
    init, end = rows[0], rows[-1]
    identity = init['kind'] == 'init' and init['schema'] == 1 and init['error'] is None \
        and init['pid'] == record['ready']['pid'] and init['qpc_frequency'] == frequency
    complete = end['kind'] == 'complete' and end['pid'] == record['ready']['pid'] \
        and end['samples_written'] == len(samples) == plan['count']
    clock_pass = 0 <= upper - lower <= plan['clock_uncertainty_ns_max']
    owner_results, brackets, widths = [], [], []
    previous = init['qpc_end']
    ordered = True
    for i, row in enumerate(samples):
        begin, finish = row['qpc_begin'], row['qpc_end']
        ordered &= row['ordinal'] == i and previous <= begin <= finish \
            and row['pid'] == record['ready']['pid']
        previous = finish
        bracket = [begin * 10**9 // frequency + lower,
                   (finish * 10**9 + frequency - 1) // frequency + upper]
        brackets.append(bracket)
        widths.append((finish - begin) * 10**6 / frequency)
        sample_record = dict(record, sampler_bracket_ns=bracket)
        owner_results.append(inspect_owner(sample_record, row['traces'], record['stderr'], plan))
    checks = dict(identity=identity, complete=complete,
        no_extra_or_error_rows=len(rows) == len(samples) + 2,
        clock_mapping=clock_pass, ordered_brackets=ordered and previous <= end.get('qpc', 0),
        all_owner_checks=bool(owner_results) and all(r['stable_correctness_pass'] for r in owner_results),
        samples_inside_external_bracket=all(record['external_bracket_ns'][0] <= b[0] <= b[1]
            <= record['external_bracket_ns'][1] for b in brackets))
    return dict(checks=checks, stable_timestamped_correctness_pass=all(checks.values()),
        samples=len(samples), clock_offset_bounds_ns=[lower, upper],
        read_bracket_us=dict(min=min(widths), median=statistics.median(widths), max=max(widths)) if widths else None,
        converted_brackets_ns=brackets,
        owner_check_failures=[dict(ordinal=i, result=r) for i, r in enumerate(owner_results)
                              if not r['stable_correctness_pass']],
        concurrent_coherence_validated=False, actual_load_disturbance_pass=False,
        field_attribution_ready=False)


def control(mode, output, tool, plan):
    target = observer = None
    folder = output / mode
    record = dict(mode=mode, errors=[], forced_cleanup=[])
    with (output / (mode + '_target.log')).open('xb') as log, \
         (output / (mode + '_observer.log')).open('xb') as observer_log:
        try:
            target = subprocess.Popen([sys.executable, str(PEER / 'fixture.py'), mode, str(folder)],
                                      stdout=log, stderr=subprocess.STDOUT)
            record['ready'] = wait_file(folder / 'ready.json', target)
            assert target.pid == record['ready']['pid'] and target.poll() is None
            (folder / 'go').touch(exist_ok=False)
            record['begin'] = wait_file(folder / 'phase_begin.json', target)
            time.sleep(.5)
            record['OS_before'] = thread_state(target.pid, record['ready']['tids']['sleeper'])
            record['anchors'] = [anchor()]
            command = [str(tool), str(target.pid), str(plan['count']), str(plan['period_ms']), str(folder / 'samples.jsonl')]
            record['command'] = command
            observations = record['heartbeat_observations'] = []
            with (folder / 'heartbeat.bin').open('rb') as backing:
                shared = mmap.mmap(backing.fileno(), 8, access=mmap.ACCESS_READ)
                try:
                    start = time.perf_counter_ns()
                    observer = subprocess.Popen(command, stdout=observer_log, stderr=subprocess.STDOUT)
                    while observer.poll() is None:
                        if time.perf_counter_ns() - start > 8 * 10**9:
                            raise TimeoutError('Observer did not finish its bounded synthetic window')
                        observations.append([time.perf_counter_ns(), struct.unpack_from('<Q', shared)[0]])
                        time.sleep(.02)
                    record['external_bracket_ns'] = [start, time.perf_counter_ns()]
                finally:
                    shared.close()
            record['anchors'].append(anchor())
            record['OS_after'] = thread_state(target.pid, record['ready']['tids']['sleeper'])
            record['sampler_returncode'] = observer.returncode
            record['target_returncode'] = target.wait(timeout=15)
            record['end'] = read(folder / 'phase_end.json')
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
    record['stderr'] = (output / (mode + '_observer.log')).read_text(errors='replace')
    write(output / (mode + '_record.json'), record)
    if record['errors'] or record['forced_cleanup']:
        return dict(stable_timestamped_correctness_pass=False, errors=record['errors'], forced_cleanup=record['forced_cleanup'])
    try:
        rows = [json.loads(line) for line in (folder / 'samples.jsonl').read_text().splitlines()]
        return inspect(record, rows, plan)
    except BaseException as exc:
        return dict(stable_timestamped_correctness_pass=False, errors=[repr(exc)])


def main(args):
    args.output.mkdir(exist_ok=False)
    lock = args.output.parent / 'active.lock'
    lock.mkdir()
    plan = read(HERE / 'stable_plan01.json')
    check_hashes = lambda: sha(args.tool) == plan['observer_sha256'] and all(
        sha(HERE.parent.parent / p) == h for p, h in plan['source_sha256'].items())
    assert check_hashes()
    assert sha(Path(sys.base_prefix) / 'python311.dll') == plan['python_dll_sha256']
    results = {}
    for mode in plan['controls']:
        results[mode] = control(mode, args.output, args.tool, plan)
        write(args.output / (mode + '_result.json'), results[mode])
        print(mode, results[mode], flush=True)
        if not results[mode]['stable_timestamped_correctness_pass']:
            break
    passed = check_hashes() and len(results) == len(plan['controls']) and all(
        r['stable_timestamped_correctness_pass'] for r in results.values())
    write(args.output / 'result.json', dict(plan_sha256=sha(HERE / 'stable_plan01.json'),
        controls=results, passed=passed, field_attribution_ready=False))
    if passed:
        lock.rmdir()
    return 0 if passed else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--tool', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    raise SystemExit(main(p.parse_args()))
