"""One prospective Walk OFF owner window. Never starts or stops the application."""
import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'native_stack_capture'))
from observe import Observer
from winapi import anchor
sys.path.insert(0, str(HERE.parent / 'gil_owner_preflight'))
from check import read, sha, write


def validate_marker(case, marker):
    if case['mode'] != 'walk' or case['trace'] != 'off' or case['run_id'] != marker['run_id']:
        raise ValueError('Expected the same newly started Walk OFF case')
    tids = marker['tids']
    if set(tids) != {'gui', 'consumer', 'reader'} or len(set(tids.values())) != 3 \
            or any(type(v) is not int or v <= 0 for v in tids.values()) \
            or type(marker['pid']) is not int or marker['pid'] <= 0:
        raise ValueError('Invalid PID/native TID identities')
    if not 0 < marker['armed_ns'] <= marker['host_ns']:
        raise ValueError('Invalid formal clock boundary')


def protocol(rows, pid, count):
    samples = [r for r in rows if r.get('kind') == 'sample']
    if not rows or len(rows) != count + 2 or len(samples) != count:
        return False
    init, end = rows[0], rows[-1]
    if init.get('kind') != 'init' or init.get('schema') != 1 or init.get('error') is not None \
            or init.get('pid') != pid or init.get('qpc_frequency', 0) <= 0 \
            or end.get('kind') != 'complete' or end.get('pid') != pid or end.get('samples_written') != count:
        return False
    previous = init['qpc_end']
    for i, row in enumerate(samples):
        if row['ordinal'] != i or row['pid'] != pid or not previous <= row['qpc_begin'] <= row['qpc_end']:
            return False
        traces = row['traces']
        if not isinstance(traces, list) or any(t.get('pid') != pid or type(t.get('os_thread_id')) is not int
                or t['os_thread_id'] <= 0 or type(t.get('owns_gil')) is not bool
                or not isinstance(t.get('frames'), list) for t in traces):
            return False
        if len({t['os_thread_id'] for t in traces}) != len(traces) or sum(t['owns_gil'] for t in traces) > 1:
            return False
        if any(t['owns_gil'] and not t['frames'] for t in traces) or any(
                not isinstance(f.get('name'), str) or not isinstance(f.get('filename'), str)
                or type(f.get('line')) is not int for t in traces for f in t['frames']):
            return False
        previous = row['qpc_end']
    return previous <= end['qpc']


def preflight(plan, tool):
    root = HERE.parent.parent
    assert ctypes.windll.shell32.IsUserAnAdmin(), 'Use the elevated desktop entry'
    assert sha(tool) == plan['observer_sha256']
    assert sha(Path(sys.base_prefix) / 'python311.dll') == plan['python_dll_sha256']
    assert all(sha(root / p) == h for p, h in plan['source_sha256'].items())
    for name, key in plan['qualifications'].items():
        data = read(root / name)
        assert sha(root / name) == plan['qualification_sha256'][name] and data[key]
    formal = Path(plan['formal_root'])
    baseline = formal / 'experiments/runtime_single_frame_fusion/baseline_manifest.json'
    frozen = formal / 'experiments/single_usb_human_etw/frozen_sources.json'
    assert sha(baseline) == plan['baseline_manifest_sha256'] and sha(frozen) == plan['formal_frozen_sha256']
    assert all(sha(formal / p) == h for p, h in read(baseline)['base_files'].items())
    assert all(sha(formal / p) == h for p, h in read(frozen)['files'].items())
    assert not (formal / 'experiments/single_usb_human_etw/active.lock').exists(), 'Formal capture lock remains; inspect, never auto-break it'
    assert not Path(plan['native_capture_lock']).exists(), 'Native CPU/wait collector lock remains'
    query = "$p=@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne $PID -and $_.CommandLine -like '*IronJump-native-stack-field-d47e067-20261017-01*'}|Select-Object ProcessId,CommandLine);ConvertTo-Json -InputObject $p -Compress"
    status = subprocess.run(['powershell', '-NoProfile', '-Command', query], capture_output=True, text=True, timeout=15)
    assert status.returncode == 0 and json.loads(status.stdout) == [], 'Existing native collector/watcher; do not overlap modes'
    return dict(static_readiness_pass=True, field_attribution_ready=False,
        actual_load_disturbance_pass=False, application_or_devices_started=False)


def capture(args, plan):
    args.output.mkdir(exist_ok=False)
    lock = args.output.parent / 'active.lock'; lock.mkdir()
    observer = child = None
    record = dict(errors=[], field_attribution_ready=False, actual_load_disturbance_pass=False)
    try:
        preflight(plan, args.tool)
        runs = Path(plan['formal_root']) / 'experiments/single_usb_human_etw/runs'
        excluded = {p.name for p in runs.iterdir() if p.is_dir()}
        write(args.output / 'watcher_ready.json', dict(pid=__import__('os').getpid(), excluded_cases=sorted(excluded),
            plan_sha256=sha(HERE / 'field_plan01.json'), scope='Wait for one manual Walk OFF; no application started'))
        deadline = time.monotonic() + plan['wait_seconds']
        selected = None
        while time.monotonic() < deadline:
            candidates = [p for p in runs.iterdir() if p.is_dir() and p.name not in excluded and (p / 'formal_started.json').exists()]
            if len(candidates) > 1:
                raise RuntimeError('Multiple new formal windows; no PID selected')
            if candidates:
                selected = candidates[0]; break
            time.sleep(.1)
        if selected is None:
            raise TimeoutError('No new manual Walk before the frozen deadline')
        marker, case = read(selected / 'formal_started.json'), read(selected / 'case.json')
        validate_marker(case, marker)
        record.update(formal_case=str(selected), formal_started=marker, case=case)
        prepare = subprocess.run(['powershell', '-NoProfile', '-File', str(HERE.parent / 'native_stack_capture/prepare_targets.ps1'),
            '-FormalStarted', str(selected / 'formal_started.json'), '-Output', str(args.output / 'targets.json')],
            capture_output=True, timeout=15)
        with (args.output / 'target_preparation.log').open('xb') as out:
            out.write(prepare.stdout + prepare.stderr)
        assert prepare.returncode == 0
        targets = read(args.output / 'targets.json')
        start_ns = marker['armed_ns'] + plan['formal_offset_ns']
        while time.perf_counter_ns() < start_ns:
            if (selected / 'trace_end_request.json').exists() or (selected / 'cancelled.json').exists():
                raise RuntimeError('Formal case ended before the requested window')
            time.sleep(.01)
        if time.perf_counter_ns() - start_ns > plan['start_lateness_ns_max']:
            raise RuntimeError('Requested window missed; no late substitute capture')
        observer = Observer(targets)
        record['anchors'] = [anchor()]
        record['before'] = observer.snapshot()
        assert all(t['active'] for t in record['before'])
        command = [str(args.tool), str(marker['pid']), str(plan['count']), str(plan['period_ms']), str(args.output / 'samples.jsonl')]
        record['command'] = command
        with (args.output / 'observer.log').open('xb') as log:
            record['external_begin_ns'] = time.perf_counter_ns()
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            record['observer_pid'] = child.pid
            # Do not kill a timed-out observer: it could be inside a process
            # suspend/read/resume bracket. Preserve its handle/PID and the lock.
            child.wait(timeout=15)
            record['external_end_ns'] = time.perf_counter_ns()
        record['observer_returncode'] = child.returncode
        record['after'] = observer.snapshot()
        record['anchors'].append(anchor())
        assert child.returncode == 0 and not (args.output / 'observer.log').read_bytes()
        assert all(a['creation_100ns'] == b['creation_100ns'] and b['active']
                   for a, b in zip(record['before'], record['after']))
        rows = [json.loads(line) for line in (args.output / 'samples.jsonl').read_text().splitlines()]
        assert protocol(rows, marker['pid'], plan['count']), 'Incomplete/failed owner stream; retain every row'
        assert sha(args.tool) == plan['observer_sha256']
        record['capture_stream_and_counters_complete'] = True
    except BaseException as exc:
        record['errors'].append(repr(exc))
    finally:
        if observer is not None:
            observer.close()
        record['observer_still_running'] = child is not None and child.poll() is None
        record['plan_sha256'] = sha(HERE / 'field_plan01.json')
        write(args.output / 'capture_record.json', record)
        if not record['errors'] and not record['observer_still_running']:
            lock.rmdir()
    print(json.dumps({k: record.get(k) for k in ('formal_case', 'errors', 'capture_stream_and_counters_complete',
        'observer_still_running', 'actual_load_disturbance_pass', 'field_attribution_ready')}, ensure_ascii=False), flush=True)
    return 1 if record['errors'] else 0


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--tool', type=Path, required=True)
    p.add_argument('--output', type=Path); p.add_argument('--check', action='store_true')
    args = p.parse_args(); plan = read(HERE / 'field_plan01.json')
    if args.check:
        print(json.dumps(preflight(plan, args.tool))); raise SystemExit(0)
    if args.output is None:
        p.error('--output required for prospective collection')
    raise SystemExit(capture(args, plan))
