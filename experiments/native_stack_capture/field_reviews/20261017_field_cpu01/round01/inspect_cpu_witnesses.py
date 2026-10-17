"""Preserve individual usable CPU-chain witnesses without declaring a hotspot share."""
import base64
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[5]
NATIVE = ROOT / 'experiments/native_stack_capture'
CASE = NATIVE / 'runs/field_cpu01_round01/split01/11948'
spec = importlib.util.spec_from_file_location('stack_analysis', NATIVE / 'analyze.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
fixture = a.read(CASE / 'fixture/fixture.json')
symbols = a.read(CASE / 'symbols03.json')
events = CASE / 'decoded/events.jsonl'
assert hashlib.sha256(events.read_bytes()).hexdigest() == symbols['events_sha256']
stacks, samples = defaultdict(list), []
with events.open() as stream:
    for line in stream:
        e = json.loads(line)
        d = base64.b64decode(e['payload'])
        if e['provider'].startswith('def2fe46'):
            q, pid, tid = struct.unpack_from('<QII', d)
            assert pid == fixture['pid']
            stacks[q, tid].append(struct.unpack_from('<' + 'Q' * ((len(d) - 16) // 8), d, 16))
        elif e['provider'].startswith('ce1dbfb4') and e['opcode'] == 46:
            ip, tid, count = struct.unpack_from('<QIH', d)
            assert count == 1
            samples.append((e['qpc'], tid, ip, bool(d[14] & 3)))
output = {'pid': fixture['pid'], 'examples': {}, 'IP_mismatches_retained': [],
          'source_events_sha256': symbols['events_sha256'],
          'scope': 'Examples are individually root-complete, unambiguous, IP-matched and non-NonProcess. They do not override the rejected global capture, estimate CPU shares, establish GIL ownership, or rank workload cost.'}
for role, t in fixture['threads'].items():
    begin, end = t['before']['clock']['qpc_after'], t['after']['clock']['qpc_before']
    tid = t['before']['tid']
    for q, thread, ip, nonprocess in samples:
        if thread != tid or not begin <= q <= end:
            continue
        parts = stacks.get((q, tid), [])
        info = a.stack_info(parts, symbols['addresses'])
        matched = any(ip in part for part in parts)
        if not matched:
            modules = [m for m in symbols['modules'] if m['base'] <= ip < m['base'] + m['size']]
            module = modules[0] if len(modules) == 1 else None
            output['IP_mismatches_retained'].append(dict(role=role, qpc=q, ip=ip,
                ip_module=module['recorded_path'] if module else None,
                ip_rva=ip-module['base'] if module else None,
                nonprocess=nonprocess, linked_frames=info['frames']))
        if not (matched and info['root_complete'] and not info['ambiguous'] and not nonprocess):
            continue
        names = [f['symbol'] or '' for f in info['frames']]
        modules = [f['module'] or '' for f in info['frames']]
        categories = []
        if role == 'gui':
            if any('QPainter::' in n or 'QRasterPaintEngine::' in n for n in names):
                categories.append('gui_paint')
            if any('QWidget::event' in n for n in names) and any('_PyEval_EvalFrameDefault' in n for n in names):
                categories.append('gui_python_widget_callback')
            if any('cv2.pyd' in m for m in modules):
                categories.append('gui_opencv_module')
        if role == 'consumer':
            if any('_PyEval_EvalFrameDefault' in n for n in names):
                categories.append('consumer_python_processing')
            if any('_multiarray_umath' in m for m in modules):
                categories.append('consumer_numpy_module')
        for category in categories:
            if category not in output['examples']:
                output['examples'][category] = dict(role=role, tid=tid, qpc=q, ip=ip, frames=info['frames'])
with Path(__file__).with_name('cpu_witnesses01.json').open('x', encoding='utf-8') as stream:
    json.dump(output, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print('Example categories:', list(output['examples']))
print('Retained IP mismatches:', len(output['IP_mismatches_retained']))
