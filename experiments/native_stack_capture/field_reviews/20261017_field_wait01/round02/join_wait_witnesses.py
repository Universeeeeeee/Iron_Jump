"""Find conservative batch-inflight witnesses in retained real field data."""
import base64
import bisect
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[5]
NATIVE = ROOT / 'experiments/native_stack_capture'
CASE = ROOT / 'experiments/single_usb_human_etw/runs/20261017_214905_5c874d97_walk_off/capture'
TRACE = NATIVE / 'runs/field_wait01_round02/split01/17752'
spec = importlib.util.spec_from_file_location('stack_analysis', NATIVE / 'analyze.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
read = analysis.read
m = read(CASE / 'measurement.json')
fixture = read(TRACE / 'fixture/fixture.json')
t = fixture['threads']['consumer']
tid = t['before']['tid']
begin, end = t['before']['clock']['qpc_after'], t['after']['clock']['qpc_before']
symbols = read(TRACE / 'symbols03.json')
events = TRACE / 'decoded/events.jsonl'
assert hashlib.sha256(events.read_bytes()).hexdigest() == symbols['events_sha256']
mapping = read(TRACE.parent / 'clock_mapping.json')
freq = mapping['qpc_frequency']
assert 1000000000 % freq == 0
factor = 1000000000 // freq
stacks, switches = defaultdict(list), []
with events.open() as stream:
    for line in stream:
        e = json.loads(line)
        provider = e['provider'][:8]
        if provider not in ('def2fe46', '3d6fa8d1'):
            continue
        d = base64.b64decode(e['payload'])
        if provider == 'def2fe46':
            q, pid, thread = struct.unpack_from('<QII', d)
            if thread == tid:
                assert pid == fixture['pid']
                stacks[q].append(struct.unpack_from('<' + 'Q' * ((len(d) - 16) // 8), d, 16))
        elif e['opcode'] == 36:
            new, old = struct.unpack_from('<II', d)
            if tid in (new, old):
                switches.append((e['qpc'], new, old, d[14]))
intervals, previous = [], None
for q, new, old, state in switches:
    if old == tid:
        previous = (q, state)
    if new == tid and previous and previous[1] == 5 and begin <= previous[0] <= q <= end:
        intervals.append((previous[0], q))
starts = [a * factor + mapping['host_ns_offset_upper'] for a, b in intervals]
witnesses = []
for row in m['queue_samples']:
    if row[9] != 'batch' or row[3] < 100 or row[8] <= 0:
        continue
    j = bisect.bisect_right(starts, row[0]) - 1
    if j < 0:
        continue
    a, b = intervals[j]
    lower = a * factor + mapping['host_ns_offset_upper']
    upper = b * factor + mapping['host_ns_offset_lower']
    if min(row[0] - lower, upper - row[0]) < 100000:
        continue
    info = analysis.stack_info(stacks.get(b, []), symbols['addresses'])
    if info['root_complete'] and not info['ambiguous'] and 'gil_wait_chain' in info['families']:
        witnesses.append(dict(host_formal_s=(row[0] - m['armed_ns']) / 1e9,
            queue_snapshot=row, switch_out_qpc=a, switch_in_qpc=b,
            conservative_interval_host_ns=[lower, upper], frames=info['frames']))
result = dict(case=CASE.parent.name, pid=fixture['pid'], tid=tid,
    mapping=mapping, guard_ns=100000, witnesses=witnesses,
    limitations=['Witnesses establish simultaneous observed pending/inflight and a paired root-complete GIL wait chain, not time percentages or GIL-owner identity.',
                 'No field-overhead calibration pass; reader CPU accounting and SDK completeness gates failed. No quantitative root-cause attribution.',
                 'Queue snapshots are low-frequency Python observations and may perturb scheduling. No missing Python function or NumPy symbol is invented.'],
    inputs_sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [events, TRACE / 'symbols03.json', CASE / 'measurement.json']})
output = Path(__file__).with_name('batch_wait_witnesses01.json')
with output.open('x', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print('Guarded GIL-wait/inflight witnesses:', len(witnesses))
for w in witnesses:
    print(w['host_formal_s'], 'pending', w['queue_snapshot'][3], 'batch', w['queue_snapshot'][10:13])
