"""Own one bounded WPR session. CPU and CSwitch profiles are mutually exclusive."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
from winapi import anchor, profile_interval

HERE = Path(__file__).resolve().parent


def main(a):
    lock = HERE / '.capture.lock'
    with lock.open('x') as stream:
        stream.write(str(a.output))
    cleanup = dict(complete=False)
    try:
        _record(a, cleanup)
    finally:
        if cleanup['complete']:
            lock.unlink()


def _record(a, cleanup):
    if not 0 < a.seconds <= 10:
        raise ValueError('Use a short window in (0,10] seconds')
    a.output.mkdir(parents=True, exist_ok=False)
    session = 'IJNative_' + uuid.uuid4().hex
    log = dict(mode=a.mode, instance=session, start=anchor(), commands=[], cleanup_complete=False,
               human_test_started_by_tool=False, external_targets=bool(a.targets))
    log['source_sha256'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in HERE.iterdir() if p.suffix in ('.py','.wprp','.json','.cs')}
    def call(args, check=True):
        r = subprocess.run(args, capture_output=True)
        log['commands'].append(dict(args=args, returncode=r.returncode,
                                    stdout=r.stdout.decode(errors='replace'), stderr=r.stderr.decode(errors='replace')))
        if check and r.returncode:
            raise RuntimeError(log['commands'][-1])
        return r
    started, original, changed = False, None, False
    try:
        if a.mode != 'off':
            # Refuse pre-existing kernel system loggers rather than merge with or cancel them.
            status = call(['logman', 'query', '-ets'])
            log['sessions_before'] = status.stdout.decode(errors='replace')
            if any(x in log['sessions_before'].lower() for x in ('wpr_system', 'nt kernel logger', 'ij native', 'ijnative_')):
                raise RuntimeError('Existing kernel recorder; leave it untouched')
            if a.mode == 'cpu':
                original = profile_interval()
                log['interval_before_100ns'] = original
            profile = HERE / (a.mode + '.wprp')
            log['profile_sha256'] = hashlib.sha256(profile.read_bytes()).hexdigest()
            call(['wpr', '-start', str(profile) + '!Native' + a.mode, '-filemode', '-instancename', session])
            started = True
            if a.mode == 'cpu':
                log['interval_requested_100ns'] = 100000  # 10 ms / 100 Hz, verify actual events independently
                # The setter may succeed before its readback raises: restore even then.
                changed = True
                log['interval_readback_100ns'] = profile_interval(100000)
            call(['wpr', '-status', '-instancename', session])
        if a.targets:
            from observe import observe
            targets = json.loads(a.targets.read_text(encoding='utf-8-sig'))
            log['targets'] = targets
            log['synthetic_targets'] = bool(targets) and all(t.get('synthetic_only') is True for t in targets)
            log['external_observation'] = observe(targets,a.seconds)
        else:
            call([sys.executable, str(HERE / 'fixture.py'), str(a.output / 'fixture'), '--seconds', str(a.seconds)])
    except BaseException as error:
        log['failure'] = repr(error)
        raise
    finally:
        errors = []
        if started:
            log['stop_ok'] = False
            try:
                # Stop only the uniquely owned instance. Preserve failure and partial ETL.
                stopped = call(['wpr', '-stop', str(a.output / 'trace.etl'), '-instancename', session], check=False)
                log['stop_ok'] = stopped.returncode == 0
                if not log['stop_ok']:
                    raise RuntimeError('Owned WPR stop failed; inspect record.json and this instance')
            except BaseException as error:
                log['stop_error'] = repr(error)
                errors.append(log['stop_error'])
        if changed:
            log['interval_restore_ok'] = False
            try:
                log['interval_restored_100ns'] = profile_interval(original)
                log['interval_restore_ok'] = log['interval_restored_100ns'] == original
                if not log['interval_restore_ok']:
                    raise RuntimeError('Sampling interval restore readback differs from original')
            except BaseException as error:
                log['interval_restore_error'] = repr(error)
                errors.append(log['interval_restore_error'])
        log['cleanup_complete'] = (not started or log['stop_ok']) and (not changed or log['interval_restore_ok'])
        try:
            log['end'] = anchor()
        except BaseException as error:
            log['end_error'] = repr(error)
            errors.append(log['end_error'])
        (a.output / 'record.json').write_text(json.dumps(log, indent=2) + '\n')
        cleanup['complete'] = log['cleanup_complete']
        if errors and 'failure' not in log:
            raise RuntimeError('Controller finalization failed: ' + '; '.join(errors))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['off', 'cpu', 'wait'])
    p.add_argument('output', type=Path)
    p.add_argument('--seconds', type=float, default=6)
    p.add_argument('--targets', type=Path, help='Existing GUI/SDK PID/TID manifest; no target is launched')
    args = p.parse_args()
    main(args)
