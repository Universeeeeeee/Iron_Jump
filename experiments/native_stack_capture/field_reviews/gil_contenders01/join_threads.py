"""Join retained GUI-process stacks to expanded offline scheduling evidence."""
import base64
import bisect
from collections import defaultdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[4]
NATIVE = ROOT / 'experiments/native_stack_capture'
OLD = NATIVE / 'runs/field_wait01_round02/split01/17752'
NEW = NATIVE / 'runs/gil_contenders01'
spec = importlib.util.spec_from_file_location('stack_analysis', NATIVE / 'analyze.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    export = a.read(NEW / 'export01.json')
    schedule_path = NEW / 'schedule01.jsonl.gz'
    assert sha(schedule_path) == export['files']['schedule01.jsonl.gz']
    assert sha(Path(__file__).with_name('export_schedule.py')) == export['script_sha256']
    assert export['etl_sha256'] == '0e0c71ccd8f77f09075d35bdc1936a5d02290624f6765a6acd14d42881067523'
    assert not any(export['metadata'][k] for k in
                   ('header_events_lost', 'buffers_lost', 'consumer_events_lost'))
    symbols = a.read(OLD / 'symbols03.json')
    assert sha(OLD / 'decoded/events.jsonl') == symbols['events_sha256']
    old_fixture = a.read(OLD / 'fixture/fixture.json')
    begin = max(t['before']['clock']['qpc_after'] for t in old_fixture['threads'].values())
    end = min(t['after']['clock']['qpc_before'] for t in old_fixture['threads'].values())
    requested = set(export['requested_tids'])
    switches, ready, lifecycle = [], defaultdict(list), defaultdict(list)
    with gzip.open(schedule_path, 'rt') as source:
        for line in source:
            e = json.loads(line)
            d = base64.b64decode(e['payload'])
            if e['opcode'] == 36:
                assert e['version'] == 5 and len(d) == 28
                new, old = struct.unpack_from('<II', d)
                switches.append((e['qpc'], new, old, d[14], e['cpu']))
            elif e['opcode'] == 50:
                assert e['version'] == 2 and len(d) == 8
                ready[struct.unpack_from('<I', d)[0]].append(e['qpc'])
            elif e['opcode'] in (1, 2, 3, 4):
                pid, tid = struct.unpack_from('<II', d)
                assert pid == 17752 and e['version'] == 3
                lifecycle[tid].append((e['qpc'], e['opcode']))
    assert set(lifecycle) == requested
    assert all(sum(op == 1 for _, op in rows) <= 1 and sum(op == 2 for _, op in rows) <= 1
               for rows in lifecycle.values()), 'Possible thread-ID reuse requires explicit handling'
    stacks = defaultdict(list)
    with (OLD / 'decoded/events.jsonl').open() as source:
        for line in source:
            e = json.loads(line)
            if e['provider'].startswith('def2fe46'):
                d = base64.b64decode(e['payload'])
                q, pid, tid = struct.unpack_from('<QII', d)
                assert pid == 17752 and tid in requested
                stacks[q, tid].append(struct.unpack_from('<' + 'Q' * ((len(d) - 16) // 8), d, 16))
    waiting, running, last_out, last_in = defaultdict(list), defaultdict(list), {}, {}
    representatives = {}
    for q, new, old, state, cpu in switches:
        if old in last_in:
            start, core = last_in.pop(old)
            assert core == cpu
            running[old].append((start, q, cpu))
        if old in requested:
            last_out[old] = (q, state)
        if new in requested:
            assert new not in last_in
            last_in[new] = (q, cpu)
        if new in last_out and last_out[new][1] == 5:
            start = last_out[new][0]
            if not begin <= start < q <= end:
                continue
            info = a.stack_info(stacks.get((q, new), []), symbols['addresses'])
            if not info['root_complete'] or info['ambiguous'] or 'gil_wait_chain' not in info['families']:
                continue
            j = bisect.bisect_right(ready[new], start)
            if j == len(ready[new]) or ready[new][j] > q:
                continue
            wake = ready[new][j]
            waiting[new].append((start, wake, q))
            representatives.setdefault(new, dict(tid=new, switch_out_qpc=start,
                ready_qpc=wake, switch_in_qpc=q,
                frames=[{k: f.get(k) for k in ('module', 'rva', 'symbol', 'pdb_matched')}
                        for f in info['frames']]))
    prior = a.read(NATIVE / 'field_reviews/20261017_field_wait01/round02/batch_wait_witnesses01.json')
    mapping = prior['mapping']
    assert mapping['qpc_frequency'] == 10000000
    guard = 1000  # 100us, with the complete host/QPC uncertainty interval retained.
    simultaneous = []
    for witness in prior['witnesses']:
        host = witness['queue_snapshot'][0]
        lo = (host - mapping['host_ns_offset_upper'] + 99) // 100
        hi = (host - mapping['host_ns_offset_lower']) // 100
        blocked = {str(tid): next(((start, wake, finish) for start, wake, finish in rows
                                  if start + guard <= lo <= hi <= wake - guard), None)
                   for tid, rows in waiting.items()}
        active = {str(tid): next(((start, finish, cpu) for start, finish, cpu in rows
                                 if start + guard <= lo <= hi <= finish - guard), None)
                  for tid, rows in running.items() if tid in requested}
        simultaneous.append(dict(host_formal_s=witness['host_formal_s'], qpc_bounds=[lo, hi],
            pending=witness['queue_snapshot'][3],
            before_ready_GIL_waits={tid: row for tid, row in blocked.items() if row},
            scheduled_running={tid: row for tid, row in active.items() if row}))
    result = dict(pid=17752, common_counter_window_qpc=[begin, end], guard_qpc_ticks=guard,
        lifecycle_tids=len(requested), tids_with_retained_stacks=len({tid for q, tid in stacks}),
        complete_GIL_wait_representatives=representatives, simultaneous=simultaneous,
        export=dict(etl_sha256=export['etl_sha256'], reader_sha256=export['reader_sha256'],
                    requested_tids=export['requested_tids'], command=export['command']),
        input_sha256={str(path.relative_to(ROOT)): sha(path) for path in
                      [schedule_path, NEW / 'export01.json', OLD / 'decoded/events.jsonl',
                       OLD / 'symbols03.json', OLD / 'fixture/fixture.json']},
        limits=['A stack at switch-in and its paired Waiting/out plus ReadyThread establish a blocked-call witness, not lock ownership.',
                'Running threads are co-scheduled candidates only: native code can run without the GIL; a preempted thread can hold it. Other processes do not share this GIL.',
                'No thread counters for added TIDs; existing reader counter, SDK completeness and actual-load calibration failures remain. No wait/CPU percentages or dominant-cause ranking.',
                '100us guard intentionally omits boundary/short intervals. This is not exhaustive evidence of every contender or every wait.'])
    output = Path(__file__).with_name('joined01.json')
    with output.open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    print('Complete same-PID GIL wait paths:', sorted(representatives))
    for row in simultaneous:
        print(row['host_formal_s'], 'blocked', list(row['before_ready_GIL_waits']),
              'co-scheduled', list(row['scheduled_running']))


if __name__ == '__main__':
    main()
