"""One frozen correctness control per mode; no field process or tracing access."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    with path.open('x') as out:
        json.dump(value, out, indent=2)
        out.write('\n')


def wait_file(path, target):
    deadline = time.monotonic() + 15
    while not path.exists():
        if target.poll() is not None:
            raise RuntimeError('Synthetic target exited before ' + path.name)
        if time.monotonic() > deadline:
            raise TimeoutError(path.name)
        time.sleep(.02)
    return read(path)


def thread_state(pid, tid):
    # Independent OS evidence that the intended worker actually entered Sleep.
    command = (f"$t=(Get-Process -Id {pid}).Threads|Where-Object {{$_.Id -eq {tid}}};"
               "@{state=[string]$t.ThreadState;reason=[string]$t.WaitReason}|ConvertTo-Json -Compress")
    run = subprocess.run(['powershell', '-NoProfile', '-Command', command],
                         capture_output=True, text=True, timeout=10, check=True)
    return json.loads(run.stdout)


def control(mode, output, tool):
    folder = output / mode
    target, sampler = None, None
    with (output / (mode + '_target.log')).open('xb') as target_log, \
         (output / (mode + '_sampler.log')).open('xb') as sampler_log:
        try:
            target = subprocess.Popen([sys.executable, str(HERE / 'fixture.py'), mode, str(folder)],
                                      stdout=target_log, stderr=subprocess.STDOUT)
            ready = wait_file(folder / 'ready.json', target)
            assert target.pid == ready['pid']
            (folder / 'go').touch(exist_ok=False)
            begin = wait_file(folder / 'phase_begin.json', target)
            time.sleep(.5)
            state_before = thread_state(target.pid, ready['tids']['sleeper'])
            command = [str(tool), 'record', '--pid', str(target.pid), '--format', 'speedscope',
                       '--full-filenames', '--threads', '--idle', '--gil', '--nonblocking',
                       '--rate', '49', '--duration', '2', '--output', str(folder / 'profile.json')]
            observations = []
            with (folder / 'heartbeat.bin').open('rb') as backing:
                shared = mmap.mmap(backing.fileno(), 8, access=mmap.ACCESS_READ)
                start = time.perf_counter_ns()
                sampler = subprocess.Popen(command, stdout=sampler_log, stderr=subprocess.STDOUT)
                while sampler.poll() is None:
                    if time.perf_counter_ns() - start > 10000000000:
                        raise TimeoutError('Synthetic sampler did not finish its two-second window')
                    observations.append([time.perf_counter_ns(), struct.unpack_from('<Q', shared)[0]])
                    time.sleep(.05)
                finish = time.perf_counter_ns()
                shared.close()
            state_after = thread_state(target.pid, ready['tids']['sleeper'])
            sampler_code = sampler.wait(timeout=5)
            target_code = target.wait(timeout=15)
            end = read(folder / 'phase_end.json')
            record = dict(mode=mode, ready=ready, begin=begin, end=end,
                sampler_bracket_ns=[start, finish], heartbeat_observations=observations,
                OS_thread_state_before=state_before, OS_thread_state_after=state_after,
                command=command, sampler_returncode=sampler_code, target_returncode=target_code)
            write(folder / 'record.json', record)
            return record
        finally:
            # Cleanup only subprocess handles created by this invocation.
            for child in (sampler, target):
                if child is not None and child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)


def inspect(record, output, plan):
    mode = record['mode']
    profile = read(output / mode / 'profile.json')
    frames = profile['shared']['frames']
    relevant, unexpected = 0, []
    samples = []
    for thread in profile['profiles']:
        match = re.search(r'Thread\s+(0[xX][0-9a-fA-F]+|\d+)', thread['name'])
        tid = int(match[1], 0) if match else None
        for stack in thread['samples']:
            names = [frames[i]['name'] for i in stack]
            if 'held_sleep' in names or 'released_sleep' in names:
                if tid != record['ready']['tids']['sleeper']:
                    unexpected.append(dict(tid=tid, names=names))
                relevant += 1
        samples.append(dict(name=thread['name'], tid=tid, captured_samples=len(thread['samples'])))
    log = (output / (mode + '_sampler.log')).read_text(errors='replace')
    error = re.search(r'Samples:\s*(\d+)\s+Errors:\s*(\d+)', log)
    values = [v for _, v in record['heartbeat_observations']]
    delta = values[-1] - values[0]
    checks = dict(processes_succeeded=record['sampler_returncode'] == record['target_returncode'] == 0,
        sampler_inside_sleep_bracket=record['begin']['host_ns'] + 200000000 < record['sampler_bracket_ns'][0]
            < record['sampler_bracket_ns'][1] < record['end']['host_ns'] - 200000000,
        OS_sleep_before_after=all(v == {'state': 'Wait', 'reason': 'ExecutionDelay'} for v in
                                 (record['OS_thread_state_before'], record['OS_thread_state_after'])),
        heartbeat_observation_floor=len(values) >= plan['heartbeat_observation_floor'],
        heartbeat_delivery=(delta == 0 if mode == 'held' else delta >= plan['released_heartbeat_increment_floor']),
        no_known_wrong_TID=not unexpected,
        held_has_no_other_GIL_thread=(mode != 'held' or not any(
            row['captured_samples'] and row['tid'] != record['ready']['tids']['sleeper'] for row in samples)),
        expected_GIL_filter=(relevant >= plan['held_sample_floor'] if mode == 'held' else relevant == 0),
        sampler_reported_no_errors=bool(error) and int(error[2]) == 0)
    return dict(mode=mode, checks=checks, correctness_pass=all(checks.values()),
        sleep_thread_samples=relevant, heartbeat_increment=delta, profile_threads=samples,
        log_tail=log.splitlines()[-10:], unexpected=unexpected,
        scope='Synthetic correctness only; samples are not elapsed GIL time or a field disturbance calibration.')


def main(args):
    args.output.mkdir(exist_ok=False)
    plan_path = HERE / 'plan01.json'
    plan = read(plan_path)
    assert sha(args.tool) == plan['py_spy_sha256']
    assert sha(Path(sys.base_prefix) / 'python311.dll') == plan['python_dll_sha256']
    assert all(sha(HERE / name) == value for name, value in plan['source_sha256'].items())
    results = []
    for mode in plan['controls']:
        record = control(mode, args.output, args.tool)
        results.append(inspect(record, args.output, plan))
        print(mode, results[-1]['checks'], flush=True)
    assert sha(args.tool) == plan['py_spy_sha256']
    assert all(sha(HERE / name) == value for name, value in plan['source_sha256'].items())
    write(args.output / 'result.json', dict(plan_sha256=sha(plan_path), controls=results,
        synthetic_correctness_pass=all(r['correctness_pass'] for r in results),
        field_attribution_ready=False, actual_load_calibration_passed=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tool', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
