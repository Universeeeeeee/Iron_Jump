"""Exact QLabel wrapper plus old same-trace Waiting/Ready evidence only."""
import base64
import bisect
from collections import defaultdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
from disassemble import pe

HERE = Path(__file__).resolve().parent
RAW = HERE/'runs/qt_label_review02'
ROOT = HERE.parents[1]
NATIVE = ROOT/'experiments/native_stack_capture'
read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def imports(data):
    _, offset, _ = pe(data)
    h = struct.unpack_from('<I', data, 60)[0]
    rva, size = struct.unpack_from('<II', data, h+24+112+8)
    cstr = lambda r: data[offset(r):data.index(b'\0', offset(r))].decode()
    result = {}
    for i in range(size//20):
        original, timestamp, chain, name, iat = struct.unpack_from('<IIIII', data, offset(rva)+20*i)
        if not any((original, timestamp, chain, name, iat)): break
        j = 0
        while True:
            pointer = struct.unpack_from('<Q', data, offset(original)+8*j)[0]
            if not pointer: break
            result[iat+8*j] = dict(dll=cstr(name), name='ordinal'+str(pointer & 65535) if pointer >> 63 else cstr(pointer+2))
            j += 1
    return result


def exports(data):
    _, offset, _ = pe(data)
    h = struct.unpack_from('<I', data, 60)[0]
    rva, size = struct.unpack_from('<II', data, h+24+112)
    fields = struct.unpack_from('<IIHHIIIIIII', data, offset(rva))
    _, names, functions, pointers, ordinals = fields[6:]
    result = {}
    for i in range(names):
        p = struct.unpack_from('<I', data, offset(pointers)+4*i)[0]
        name = data[offset(p):data.index(b'\0', offset(p))].decode()
        ordinal = struct.unpack_from('<H', data, offset(ordinals)+2*i)[0]
        result[name] = struct.unpack_from('<I', data, offset(functions)+4*ordinal)[0]
    return result


def instructions(path, begin, end):
    data = path.read_bytes(); base, offset, _ = pe(data)
    raw = subprocess.run(['/usr/bin/objdump', '-d', f'--start-address={hex(base+begin)}',
        f'--stop-address={hex(base+end)}', str(path)], check=True, capture_output=True, text=True).stdout
    with (RAW/f'{path.name}_{begin:x}_qtlabel.txt').open('x') as f: f.write(raw)
    rows = []
    table = imports(data)
    for line in raw.splitlines():
        m = re.match(r'^([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)$', line)
        if not m: continue
        rva = int(m.group(1), 16)-base; code = bytes.fromhex(m.group(2))
        assert data[offset(rva):offset(rva)+len(code)] == code
        row = dict(rva=rva, bytes=code.hex(), instruction=m.group(3))
        prefix = 1 if code[:1] == b'\x48' else 0
        if code[prefix:prefix+2] in (b'\xff\x15', b'\xff\x25') and len(code) == 6+prefix:
            at = rva+len(code)+struct.unpack_from('<i', code, prefix+2)[0]
            row.update(iat_rva=at, imported_target=table.get(at))
        rows.append(row)
    return rows


def required_matched(frames, required):
    return all(any(f.get('symbol') == name and f.get('pdb_matched') for f in frames) for name in required)


def guarded_overlap(a, b, guard=1000):
    lo, hi = max(a['out_qpc'], b['out_qpc'])+guard, min(a['ready_qpc'], b['ready_qpc'])-guard
    return [lo, hi] if lo <= hi else None


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('old_native_quality', NATIVE/'analyze.py')
    analysis = importlib.util.module_from_spec(spec); spec.loader.exec_module(analysis)
    old = NATIVE/'runs/field_wait01_round02/split01/17752'
    symbols = read(old/'symbols03.json'); events_path = old/'decoded/events.jsonl'
    assert sha(events_path) == symbols['events_sha256']
    schema = read(HERE/'label_boundary01.json')
    assert schema['script_sha256'] == sha(HERE/'inspect_label_boundary.py') and schema['field_return_inside_entry']
    for name in ('QtWidgets.pyd', 'shiboken6.abi3.dll'):
        module = next(m for m in symbols['modules'] if m.get('path', '').endswith(name))
        assert sha(HERE/'runs'/name) == module['sha256']
    assert schema['module_sha256'] == sha(HERE/'runs/QtWidgets.pyd')
    RAW.mkdir()
    wrapper = instructions(HERE/'runs/QtWidgets.pyd', *schema['unwind_range'][:2])
    by = {v['rva']:v for v in wrapper}
    assert by[0x1a8771]['imported_target'] == dict(dll='Qt6Widgets.dll', name='?paintEvent@QLabel@@MEAAXPEAVQPaintEvent@@@Z')
    assert by[0x1a875e]['imported_target']['name'] == '?occurred@Errors@Shiboken@@YAPEAU_object@@XZ'
    assert by[0x1a8777]['imported_target']['name'] == 'Sbk_ReturnFromPython_None'
    assert not any(v.get('imported_target', {}).get('name') in ('PyEval_SaveThread', 'PyEval_RestoreThread') for v in wrapper)
    # The exact context guard is a leaf TLS operation, not a hidden GIL release.
    helpers = exports((HERE/'runs/shiboken6.abi3.dll').read_bytes())
    helper_entries = {n:helpers[n] for n in ('??0PythonContextMarker@Shiboken@@QEAA@XZ',
        '??1PythonContextMarker@Shiboken@@QEAA@XZ', '?occurred@Errors@Shiboken@@YAPEAU_object@@XZ')}
    assert list(helper_entries.values()) == [0x11400, 0x12730, 0x25420]
    ctor = instructions(HERE/'runs/shiboken6.abi3.dll', 0x11400, 0x1142d)
    dtor = instructions(HERE/'runs/shiboken6.abi3.dll', 0x12730, 0x1274d)
    assert all(not re.match(r'(call|j\w*)', v['instruction']) for v in ctor+dtor)
    assert ctor[-1]['bytes'] == dtor[-1]['bytes'] == 'c3'
    errors = instructions(HERE/'runs/shiboken6.abi3.dll', 0x25420, 0x254a3)
    assert errors[-1]['imported_target'] == dict(dll='python3.dll', name='PyErr_Occurred')
    delivered = read(HERE/'error_api01.json')
    assert delivered['script_sha256'] == sha(HERE/'inspect_error_api.py')
    assert delivered['shiboken_sha256'] == sha(HERE/'runs/shiboken6.abi3.dll')
    assert all(v['matches_CPython_export'] for v in delivered['targets'])
    # After the error check, only a conditional branch and argument moves precede
    # the exact QLabel native call. Do not infer historical ownership from this.
    bridge = [v for v in wrapper if 0x1a8764 <= v['rva'] <= 0x1a8771]
    assert [v['rva'] for v in bridge] == [0x1a8764, 0x1a8767, 0x1a8769, 0x1a876e, 0x1a8771]
    fixture = read(old/'fixture/fixture.json')['threads']
    begin = max(v['before']['clock']['qpc_after'] for v in fixture.values())
    end = min(v['after']['clock']['qpc_before'] for v in fixture.values())
    parts = defaultdict(list)
    for line in events_path.open():
        e = json.loads(line)
        if e['provider'].startswith('def2fe46'):
            b = base64.b64decode(e['payload']); q, pid, tid = struct.unpack_from('<QII', b)
            assert pid == 17752
            if tid in (20420, 5376): parts[q, tid].append(struct.unpack_from('<'+'Q'*((len(b)-16)//8), b, 16))
    schedule = NATIVE/'runs/gil_contenders01/schedule01.jsonl.gz'
    export = read(schedule.parent/'export01.json')
    assert sha(schedule) == export['files']['schedule01.jsonl.gz']
    switches, ready = [], defaultdict(list)
    with gzip.open(schedule, 'rt') as f:
        for line in f:
            e = json.loads(line); b = base64.b64decode(e['payload'])
            if e['opcode'] == 36:
                new, old_tid = struct.unpack_from('<II', b)
                if {new, old_tid} & {20420, 5376}: switches.append((e['qpc'], new, old_tid, b[14]))
            elif e['opcode'] == 50: ready[struct.unpack_from('<I', b)[0]].append(e['qpc'])
    groups = {20420:[], 5376:[]}; last = {}
    for q, new, old_tid, state in switches:
        last[old_tid] = (q, state)
        previous = last.pop(new, None)
        if new not in groups or previous is None: continue
        start, out_state = previous
        if out_state != 5 or not begin <= start < q <= end: continue
        info = analysis.stack_info(parts.get((q, new), []), symbols['addresses'])
        if not info['root_complete'] or info['ambiguous']: continue
        required = ['QLatch::waitInternal', 'WaitOnAddress', 'QLabel::paintEvent', 'QPixmap::scaled', 'QImage::smoothScaled'] if new == 20420 else ['take_gil', 'NtWaitForSingleObject']
        if not required_matched(info['frames'], required): continue
        if new == 5376 and 'gil_wait_chain' not in info['families']: continue
        if new == 20420 and not any(f['module'] == 'QtWidgets.pyd' and f['rva'] == 0x1a8777 for f in info['frames']): continue
        i = bisect.bisect_right(ready[new], start)
        if i == len(ready[new]) or ready[new][i] > q: continue
        groups[new].append(dict(tid=new, out_qpc=start, ready_qpc=ready[new][i], in_qpc=q,
            frames=[{k:f.get(k) for k in ('module','rva','symbol','pdb_matched')} for f in info['frames']]))
    overlaps = []
    for gi, gui in enumerate(groups[20420]):
        for ci, consumer in enumerate(groups[5376]):
            bounds = guarded_overlap(gui, consumer)
            if bounds: overlaps.append(dict(gui_wait_index=gi, consumer_wait_index=ci, guarded_common_before_Ready_qpc=bounds))
    original = NATIVE/'field_reviews/20261017_field_wait01/round02/batch_wait_witnesses01.json'
    prior = read(original); mapping = prior['mapping']; points = []
    assert all(sha(ROOT/n) == v for n,v in prior['inputs_sha256'].items())
    for v in prior['witnesses']:
        host = v['queue_snapshot'][0]; frequency = mapping['qpc_frequency']
        lo = -(-(host-mapping['host_ns_offset_upper'])*frequency//10**9)
        hi = (host-mapping['host_ns_offset_lower'])*frequency//10**9
        matched = [i for i,g in enumerate(groups[20420]) if g['out_qpc']+1000 <= lo <= hi <= g['ready_qpc']-1000]
        points.append(dict(formal_s=v['host_formal_s'], pending=v['queue_snapshot'][3], qpc_bounds=[lo,hi], GUI_latch_wait_indices=matched))
    result = dict(pid=17752, common_counter_window_qpc=[begin,end], public_wrapper=schema,
        exact_wrapper_instructions=wrapper, helper_export_entries=helper_entries, context_guard_constructor=ctor, context_guard_destructor=dtor,
        pre_native_error_helper=errors, loaded_stable_ABI_targets=delivered, no_explicit_wrapper_GIL_release=True, native_call_bridge=bridge,
        GUI_QLatch_waits=groups[20420], consumer_GIL_waits=groups[5376], guarded_simultaneous_waits=overlaps,
        six_existing_batch_pending_points=points, guard_qpc_ticks=1000,
        limits=['The public native call has no explicit SaveThread bridge; the normal CPython method-entry GIL contract is a static mechanism constraint, not a direct historical owner snapshot.',
            'Qt latch waits and consumer GIL waits are distinct Waiting paths. Ready-to-in is not counted as GIL Waiting.',
            'A simultaneous scheduler intersection does not identify the GIL owner, wake source, same image job or root contribution.',
            'No prior pending point is promoted to a QLabel witness unless its full clock bracket and guard match.',
            'Old stack and actual-load3%/1% failures remain failed. No duration shares, CPU percentages or formal fix follow.'],
        bindings={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__), HERE/'inspect_label_boundary.py', HERE/'label_boundary01.json',
            HERE/'inspect_error_api.py', HERE/'error_api01.json', HERE/'qt_label_preparation_failure01.json',
            NATIVE/'analyze.py', old/'symbols03.json', events_path, old/'fixture/fixture.json', schedule, schedule.parent/'export01.json', original]},
        new_capture=False, direct_historical_owner_identified=False, primary_root_identified=False, field_fix_verified=False)
    with (HERE/'qt_label_wait01.json').open('x') as f: json.dump(result, f, indent=2)
    print(json.dumps(dict(GUI_latch_waits=len(groups[20420]), consumer_GIL_waits=len(groups[5376]),
        guarded_intersections=len(overlaps), original_pending_points_with_GUI_latch=sum(bool(v['GUI_latch_wait_indices']) for v in points)), indent=2))
