"""Annotate existing complete field chains using independently read C entries."""
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
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('stack_analysis', NATIVE / 'analyze.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stacks(path, tids):
    result = defaultdict(list)
    with path.open() as source:
        for line in source:
            e = json.loads(line)
            if e['provider'].startswith('def2fe46'):
                data = base64.b64decode(e['payload'])
                q, pid, tid = struct.unpack_from('<QII', data)
                if tid in tids:
                    result[q, tid].append(struct.unpack_from('<' + 'Q' * ((len(data) - 16) // 8), data, 16))
    return result


def main():
    mapping = a.read(HERE / 'entry_map01.json')
    assert mapping['script_sha256'] == sha(HERE / 'map_entries.py')
    old = NATIVE / 'runs/field_wait01_round02/split01/17752'
    symbols = a.read(old / 'symbols03.json')
    event_path = old / 'decoded/events.jsonl'
    assert sha(event_path) == symbols['events_sha256']
    assert next(m['sha256'] for m in symbols['modules'] if m.get('path', '').endswith('cv2.pyd')) == mapping['sha256']
    fixtures = a.read(old / 'fixture/fixture.json')['threads']
    begin = max(t['before']['clock']['qpc_after'] for t in fixtures.values())
    end = min(t['after']['clock']['qpc_before'] for t in fixtures.values())
    parts = stacks(event_path, {20420, 13080, 17236})
    switches, ready = [], defaultdict(list)
    schedule = NATIVE / 'runs/gil_contenders01/schedule01.jsonl.gz'
    export = a.read(NATIVE / 'runs/gil_contenders01/export01.json')
    assert sha(schedule) == export['files']['schedule01.jsonl.gz']
    with gzip.open(schedule, 'rt') as source:
        for line in source:
            e = json.loads(line)
            d = base64.b64decode(e['payload'])
            if e['opcode'] == 36:
                new, old_tid = struct.unpack_from('<II', d)
                switches.append((e['qpc'], new, old_tid, d[14]))
            elif e['opcode'] == 50:
                ready[struct.unpack_from('<I', d)[0]].append(e['qpc'])

    def public_names(info):
        rvas = [f['rva'] for f in info['frames'] if f['module'] == 'cv2.pyd']
        return sorted({entry['name'] for entry in mapping['entries'] if entry['unwind_range']
                       and any(entry['unwind_range'][0] <= r < entry['unwind_range'][1] for r in rvas)})

    examples, last_out, all_qualified = {}, {}, {}
    for q, new, old_tid, state in switches:
        last_out[old_tid] = (q, state)
        if new not in (20420, 13080, 17236) or new not in last_out:
            continue
        start, previous = last_out[new]
        if previous != 5 or not begin <= start < q <= end:
            continue
        info = a.stack_info(parts.get((q, new), []), symbols['addresses'])
        if not info['root_complete'] or info['ambiguous'] or 'gil_wait_chain' not in info['families']:
            continue
        names = public_names(info)
        if not names:
            continue
        i = bisect.bisect_right(ready[new], start)
        if i == len(ready[new]) or ready[new][i] > q:
            continue
        symbols_in_chain = [f['symbol'] for f in info['frames']]
        boundary = 'PyGILState_Ensure' if 'PyGILState_Ensure' in symbols_in_chain else 'PyEval_RestoreThread'
        assert boundary in symbols_in_chain
        assert all(f.get('pdb_matched') for f in info['frames'] if f['symbol'] in ('take_gil', boundary))
        row = dict(pid=17752, tid=new, switch_out_qpc=start, ready_qpc=ready[new][i],
            switch_in_qpc=q, public_entry_names=names, GIL_boundary=boundary,
            frames=[{k: f.get(k) for k in ('module', 'rva', 'symbol', 'pdb_matched')} for f in info['frames']])
        all_qualified[q, new] = row
        examples.setdefault((new, tuple(names), boundary), row)
    prior = a.read(NATIVE / 'field_reviews/gil_contenders01/joined01.json')
    point = next(row for row in prior['simultaneous'] if row['host_formal_s'] == 13.8641344)
    start, wake, finish = point['before_ready_GIL_waits']['13080']
    overlap = all_qualified[finish, 13080]
    assert overlap['public_entry_names'] == ['cv2.imdecode']
    assert (start, wake) == (overlap['switch_out_qpc'], overlap['ready_qpc'])
    assert start + 1000 <= point['qpc_bounds'][0] <= point['qpc_bounds'][1] <= wake - 1000
    cpu_path = NATIVE / 'runs/field_cpu01_round01/split01/11948'
    cpu_symbols = a.read(cpu_path / 'symbols03.json')
    cpu_events = cpu_path / 'decoded/events.jsonl'
    assert sha(cpu_events) == cpu_symbols['events_sha256']
    cpu = a.read(NATIVE / 'field_reviews/20261017_field_cpu01/round01/cpu_witnesses01.json')['examples']['gui_opencv_module']
    cpu_parts = stacks(cpu_events, {cpu['tid']})[cpu['qpc'], cpu['tid']]
    info = a.stack_info(cpu_parts, cpu_symbols['addresses'])
    assert info['root_complete'] and not info['ambiguous'] and any(cpu['ip'] in p for p in cpu_parts)
    assert next(m['sha256'] for m in cpu_symbols['modules'] if m.get('path', '').endswith('cv2.pyd')) == mapping['sha256']
    assert public_names(info) == ['cv2.resize']
    result = dict(wait_examples=list(examples.values()), pending_overlap=dict(
        formal_s=point['host_formal_s'], pending=point['pending'], batch_size=20,
        before_ready_participants=list(point['before_ready_GIL_waits']),
        imdecode_wait=overlap, qpc_bounds=point['qpc_bounds'], guard_qpc_ticks=1000),
        separate_CPU_round_example=dict(pid=11948, tid=cpu['tid'], qpc=cpu['qpc'],
            ip=cpu['ip'], matched_public_entry='cv2.resize', root_and_IP_match_rechecked=True),
        input_sha256={str(p.relative_to(ROOT)): sha(p) for p in
                      [event_path, old / 'symbols03.json', schedule, cpu_events,
                       cpu_path / 'symbols03.json', HERE / 'entry_map01.json']},
        limits=['Public entry annotations are independent of PDB naming; all unknown internal frames retain module+RVA.',
                'Wait paths establish reacquisition at return and within native OpenCV calls, not GIL ownership or exclusive native execution cost.',
                'CPU and wait examples are different trials and cannot be combined into synchronous attribution or shares. Original rejected acceptance remains unchanged.'])
    with (HERE / 'witnesses01.json').open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    print('Qualified wait families:', [(k[0], k[1], k[2]) for k in examples])
    print('pending672 overlap: imdecode returns to the GIL on TID13080; separate GUI CPU witness is resize.')


if __name__ == '__main__':
    main()
