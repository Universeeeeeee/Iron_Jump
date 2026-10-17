"""One default-mode dump per synthetic control; never attaches to a supplied PID."""
import argparse
import json
import mmap
from pathlib import Path
import struct
import subprocess
import sys
import time

from check import read, sha, thread_state, wait_file, write

HERE = Path(__file__).resolve().parent


def inspect(record, traces, stderr, plan):
    expected = record['ready']['tids']['sleeper']
    schema = isinstance(traces, list) and bool(traces) and all(
        isinstance(t, dict) and type(t.get('owns_gil')) is bool
        and type(t.get('os_thread_id')) is int and t['os_thread_id'] > 0
        and t.get('pid') == record['ready']['pid'] and isinstance(t.get('frames'), list)
        and all(isinstance(f, dict) and isinstance(f.get('name'), str)
                and isinstance(f.get('filename'), str) and type(f.get('line')) is int
                for f in t['frames']) for t in traces)
    owners = [t for t in traces if t.get('owns_gil') is True] if schema else []
    sleeper = [t for t in traces if t['os_thread_id'] == expected] if schema else []
    held = record['mode'] == 'held'
    heartbeat = record['heartbeat_observations']
    delta = heartbeat[-1][1] - heartbeat[0][1]
    bracket = record['sampler_bracket_ns']
    checks = dict(schema_and_PID=schema,
        unique_native_TIDs=schema and len({t['os_thread_id'] for t in traces}) == len(traces),
        known_sleep_frame=len(sleeper) == 1 and any(
            f['name'] == record['mode'] + '_sleep' for f in sleeper[0]['frames']),
        known_owner=(len(owners) == 1 and owners[0]['os_thread_id'] == expected
                     if held else all(t['os_thread_id'] != expected for t in owners)),
        at_most_one_owner=len(owners) <= 1,
        heartbeat_delivery=(delta == 0 if held else delta >= plan['released_heartbeat_increment_floor']),
        sleep_OS_before_after=all(v == {'state': 'Wait', 'reason': 'ExecutionDelay'} for v in
                                  (record['OS_before'], record['OS_after'])),
        bracket_inside_phase=record['begin']['host_ns'] + plan['phase_margin_ns'] < bracket[0]
            < bracket[1] < record['end']['host_ns'] - plan['phase_margin_ns'],
        target_executed_after_dump=record['end']['host_ns'] > bracket[1]
            and record['complete']['completed'] and record['complete']['pid'] == record['ready']['pid'],
        processes_exited=record['target_returncode'] == record['sampler_returncode'] == 0,
        no_stderr=not stderr.strip(),
        no_error_or_forced_cleanup=not record.get('errors') and not record.get('forced_cleanup'))
    return dict(checks=checks, stable_correctness_pass=all(checks.values()),
        owner_native_TIDs=[t['os_thread_id'] for t in owners], heartbeat_increment=delta,
        observation_bracket_ns=bracket, field_attribution_ready=False,
        concurrent_mutating_frames_validated=False, actual_load_disturbance_pass=False)


def control(mode, output, tool, plan):
    folder = output / mode
    target = sampler = None
    record = dict(mode=mode, errors=[], forced_cleanup=[])
    with (output / (mode + '_target.log')).open('xb') as log, \
         (output / (mode + '_dump.json')).open('xb') as dump, \
         (output / (mode + '_stderr.log')).open('xb') as stderr:
        try:
            target = subprocess.Popen([sys.executable, str(HERE / 'fixture.py'), mode, str(folder)],
                                      stdout=log, stderr=subprocess.STDOUT)
            ready = wait_file(folder / 'ready.json', target)
            assert target.pid == ready['pid'] and target.poll() is None
            record['ready'] = ready
            (folder / 'go').touch(exist_ok=False)
            record['begin'] = wait_file(folder / 'phase_begin.json', target)
            time.sleep(.5)
            record['OS_before'] = thread_state(target.pid, ready['tids']['sleeper'])
            command = [str(tool), 'dump', '--pid', str(target.pid), '--json', '--full-filenames']
            record['command'] = command
            observations = record['heartbeat_observations'] = []
            with (folder / 'heartbeat.bin').open('rb') as backing:
                shared = mmap.mmap(backing.fileno(), 8, access=mmap.ACCESS_READ)
                try:
                    observations.append([time.perf_counter_ns(), struct.unpack_from('<Q', shared)[0]])
                    start = time.perf_counter_ns()
                    sampler = subprocess.Popen(command, stdout=dump, stderr=stderr)
                    sampler.wait(timeout=plan['dump_timeout_s'])
                    finish = time.perf_counter_ns()
                    record['sampler_bracket_ns'] = [start, finish]
                    deadline = time.perf_counter() + .5
                    while time.perf_counter() < deadline:
                        observations.append([time.perf_counter_ns(), struct.unpack_from('<Q', shared)[0]])
                        time.sleep(.02)
                finally:
                    shared.close()
            record['OS_after'] = thread_state(target.pid, ready['tids']['sleeper'])
            record['sampler_returncode'] = sampler.returncode
            record['target_returncode'] = target.wait(timeout=15)
            record['end'] = read(folder / 'phase_end.json')
            record['complete'] = read(folder / 'complete.json')
        except BaseException as exc:
            record['errors'].append(repr(exc))
        finally:
            for name, child in (('sampler', sampler), ('target', target)):
                if child is not None and child.poll() is None:
                    record['forced_cleanup'].append(name)
                    try:
                        child.terminate()
                        child.wait(timeout=10)
                    except BaseException as exc:
                        record['errors'].append(name + ' cleanup: ' + repr(exc))
    write(output / (mode + '_record.json'), record)
    if record['errors'] or record['forced_cleanup']:
        return dict(stable_correctness_pass=False, errors=record['errors'], forced_cleanup=record['forced_cleanup'])
    try:
        return inspect(record, read(output / (mode + '_dump.json')),
                       (output / (mode + '_stderr.log')).read_text(errors='replace'), plan)
    except BaseException as exc:
        return dict(stable_correctness_pass=False, errors=[repr(exc)])


def main(args):
    args.output.mkdir(exist_ok=False)
    lock = args.output.parent / 'active.lock'
    lock.mkdir()
    plan = read(args.plan)
    assert sha(args.tool) == plan['py_spy_sha256']
    assert sha(Path(sys.base_prefix) / 'python311.dll') == plan['python_dll_sha256']
    assert all(sha(HERE / p) == h for p, h in plan['source_sha256'].items())
    results = {}
    for mode in plan['controls']:
        results[mode] = control(mode, args.output, args.tool, plan)
        write(args.output / (mode + '_result.json'), results[mode])
        print(mode, results[mode], flush=True)
        if not results[mode]['stable_correctness_pass']:
            break
    hashes_match = sha(args.tool) == plan['py_spy_sha256'] and all(
        sha(HERE / p) == h for p, h in plan['source_sha256'].items())
    passed = hashes_match and len(results) == len(plan['controls']) and all(
        r['stable_correctness_pass'] for r in results.values())
    write(args.output / 'result.json', dict(plan_sha256=sha(args.plan), controls=results,
        hashes_match=hashes_match, stable_correctness_pass=passed,
        field_attribution_ready=False, actual_load_disturbance_pass=False))
    if passed:
        lock.rmdir()
    return 0 if passed else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tool', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
