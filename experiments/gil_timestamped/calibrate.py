"""Fixed synthetic observer OFF/ON pairs; no application or device imports."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent / 'native_stack_capture'
sys.path.insert(0, str(NATIVE))
from observe import Observer
from winapi import anchor
from align_clock import mapping
from external_report import work_bounds, pair_result
sys.path.insert(0, str(HERE.parent / 'gil_owner_preflight'))
from check import read, sha, write


def case(mode, output, tool, plan):
    output.mkdir(exist_ok=False)
    fixture = output / 'synthetic'; fixture.mkdir()
    children, targets, observer = [], [], None
    data = dict(mode=mode, errors=[], forced_cleanup=[])
    try:
        for role in ('gui', 'sdk'):
            child = subprocess.Popen([sys.executable, str(NATIVE / 'external_fixture.py'), role,
                str(fixture / role), str(fixture / 'stop')], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            children.append((role, child))
            ready = json.loads(child.stdout.readline())
            assert ready['pid'] == child.pid and child.poll() is None
            targets += ready['targets']
        time.sleep(.6)  # Independent progress observations must bracket counters.
        observer = Observer(targets)
        data['anchors'] = [anchor()]
        data['before'] = observer.snapshot()
        with (output / 'observer.log').open('xb') as log:
            if mode == 'on':
                target_pid = next(t['pid'] for t in targets if t['fixture_process'] == 'gui')
                command = [str(tool), str(target_pid), str(plan['count']), str(plan['period_ms']), str(output / 'samples.jsonl')]
                run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=15)
                assert run.returncode == 0
                rows = [json.loads(line) for line in (output / 'samples.jsonl').read_text().splitlines()]
                owner_tids = {t['os_thread_id'] for r in rows if r['kind'] == 'sample'
                              for t in r['traces'] if t['owns_gil']}
                identities = Observer([dict(pid=target_pid, tid=tid, role='gui', name=str(tid)) for tid in owner_tids])
                try:
                    data['owner_identities'] = identities.snapshot()
                    assert all(t['active'] for t in data['owner_identities'])
                finally:
                    identities.close()
            else:
                time.sleep(plan['seconds'])
        data['after'] = observer.snapshot()
        data['anchors'].append(anchor())
        time.sleep(.6)
    except BaseException as exc:
        data['errors'].append(repr(exc))
    finally:
        if observer is not None:
            observer.close()
        (fixture / 'stop').touch(exist_ok=False)
        for role, child in children:
            try:
                stdout, stderr = child.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                data['forced_cleanup'].append(role)
                child.terminate(); stdout, stderr = child.communicate(timeout=10)
            write(output / (role + '_exit.json'), dict(pid=child.pid, returncode=child.returncode, stdout=stdout, stderr=stderr))
            if child.returncode or stderr:
                data['errors'].append(role + ' did not exit cleanly')
    write(output / 'record.json', data)
    assert not data['errors'] and not data['forced_cleanup'], data
    fixtures = {p: read(fixture / p / 'progress.json') for p in ('gui', 'sdk')}
    maps = [mapping(data['anchors'])] + [mapping(f['anchors']) for f in fixtures.values()]
    clock = dict(maps[0], host_ns_offset_lower=max(m['host_ns_offset_lower'] for m in maps),
                 host_ns_offset_upper=min(m['host_ns_offset_upper'] for m in maps))
    assert all(m['qpc_frequency'] == clock['qpc_frequency'] for m in maps)
    assert 0 <= clock['host_ns_offset_upper'] - clock['host_ns_offset_lower'] <= plan['clock_uncertainty_ns_max']
    protocol = True
    if mode == 'on':
        rows = [json.loads(line) for line in (output / 'samples.jsonl').read_text().splitlines()]
        samples = [r for r in rows if r['kind'] == 'sample']
        protocol = len(samples) == plan['count'] and len(rows) == len(samples) + 2 \
            and rows[0]['kind'] == 'init' and rows[0]['error'] is None \
            and rows[-1]['kind'] == 'complete' and not (output / 'observer.log').read_bytes()
        previous = rows[0]['qpc_end']
        tids = {t['tid'] for t in data['owner_identities']}
        for i, row in enumerate(samples):
            protocol &= row['ordinal'] == i and previous <= row['qpc_begin'] <= row['qpc_end']
            previous = row['qpc_end']
            owners = [t for t in row['traces'] if t['owns_gil']]
            protocol &= row['pid'] == target_pid and all(t['pid'] == target_pid for t in row['traces']) \
                and len(owners) <= 1 and all(t['os_thread_id'] in tids for t in owners)
        protocol &= previous <= rows[-1]['qpc']
    result = dict(mode=mode, clock=clock, processes={}, synthetic_only=True)
    for role in ('gui', 'sdk'):
        f = fixtures[role]; threads = {}
        for before, after in zip(data['before'], data['after']):
            if before['pid'] != f['pid']:
                continue
            assert before['tid'] == after['tid'] and before['creation_100ns'] == after['creation_100ns']
            assert before['active'] and after['active']
            threads[before['name']] = dict(tid=before['tid'],
                cpu_s=(after['user_100ns'] + after['kernel_100ns'] - before['user_100ns'] - before['kernel_100ns']) / 1e7,
                cycles=after['cycles'] - before['cycles'],
                work=work_bounds(f['history'], before['name'], before, after, clock))
        # This flag is for the reused synthetic pair comparator only. It does
        # not upgrade native ETL acceptance or qualify any field measurement.
        result['processes'][role] = dict(pid=f['pid'], threads=threads, measurement_acceptance_pass=bool(protocol))
    write(output / 'analysis.json', result)
    return result


def main(args):
    args.output.mkdir(exist_ok=False)
    lock = args.output.parent / 'active.lock'; lock.mkdir()
    plan = read(HERE / 'perturbation_plan01.json')
    def hashes():
        return sha(args.tool) == plan['observer_sha256'] and all(
            sha(HERE.parent.parent / p) == h for p, h in plan['source_sha256'].items())
    assert hashes() and sha(Path(sys.base_prefix) / 'python311.dll') == plan['python_dll_sha256']
    results = []
    for i, order in enumerate(plan['orders'], 1):
        cases = {mode: case(mode, args.output / f'pair{i}_{mode}', args.tool, plan) for mode in order}
        paired = pair_result(cases['off'], cases['on'], plan['pair_limits'])
        results.append(dict(pair=i, **paired)); print(results[-1], flush=True)
    assert hashes()
    passed = all(r['passed'] for r in results)
    write(args.output / 'result.json', dict(plan_sha256=sha(HERE / 'perturbation_plan01.json'),
        pairs=results, synthetic_perturbation_pass=passed, actual_load_disturbance_pass=False,
        field_attribution_ready=False))
    if passed:
        lock.rmdir()
    return 0 if passed else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--tool', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    raise SystemExit(main(p.parse_args()))
