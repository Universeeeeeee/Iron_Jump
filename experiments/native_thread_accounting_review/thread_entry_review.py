"""Read retained thread rundown entries; never infer a GIL owner or CPU share."""
import base64
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def layout(schema):
    parent = {q['name']: q['value'] for q in schema['parent_qualifiers']}
    assert schema['class'] == 'Thread_V3_TypeGroup1'
    assert parent['EventVersion'] == 3
    assert parent['Guid'].lower() == '{3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c}'
    fields = []
    for p in schema['properties']:
        q = {v['name']: v['value'] for v in p['qualifiers']}
        if 'WmiDataId' in q:
            code = 'Q' if q.get('pointer') else {'UInt32': 'I', 'UInt8': 'B'}[p['type']]
            fields.append((q['WmiDataId'], p['name'], code))
    fields.sort()
    assert [v[0] for v in fields] == list(range(1, 15))
    assert [v[1] for v in fields] == ['ProcessId', 'TThreadId', 'StackBase', 'StackLimit',
        'UserStackBase', 'UserStackLimit', 'Affinity', 'Win32StartAddr', 'TebBase',
        'SubProcessTag', 'BasePriority', 'PagePriority', 'IoPriority', 'ThreadFlags']
    fmt = '<' + ''.join(v[2] for v in fields)
    assert struct.calcsize(fmt) == 72
    return fmt, [v[1] for v in fields]


def decode(event, spec):
    assert event['provider'] == '3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c'
    assert event['version'] == 3 and event['opcode'] in (1, 2, 3, 4)
    assert event['flags'] & 0x40  # Pointer-qualified WMI fields are 64 bits.
    data = base64.b64decode(event['payload'], validate=True)
    fmt, names = spec
    assert len(data) >= struct.calcsize(fmt)
    return dict(zip(names, struct.unpack_from(fmt, data))), data[struct.calcsize(fmt):].hex()


def module_at(address, modules):
    found = [m for m in modules if m['base'] <= address < m['base'] + m['size']]
    if len(found) != 1:
        return dict(address=address, module=None, rva=None, sha256=None, ambiguous=bool(found))
    m = found[0]
    return dict(address=address, module=m.get('path', m['recorded_path']),
                rva=address-m['base'], sha256=m.get('sha256'), ambiguous=False)


if __name__ == '__main__':
    plan = read(HERE/'expanded_review_plan01.json')
    assert all(sha(ROOT/n) == v for n, v in plan['bindings'].items())
    schema = read(HERE/'thread_start_schema01.json')
    assert schema['query_sha256'] == sha(HERE/'read_thread_schema01.ps1')
    spec = layout(schema['schema'])
    events = [json.loads(s) for s in (HERE/'runs/events.jsonl').read_text().splitlines()]
    symbols_path = ROOT/'experiments/native_stack_capture/runs/field_cpu01_round01/split01/11948/symbols03.json'
    symbols = read(symbols_path)
    fixture_path = symbols_path.parent/'fixture/fixture.json'
    named = {v['before']['tid']:name for name,v in read(fixture_path)['threads'].items()}
    review = read(HERE/'expanded_cpu_review01.json')
    assert all(sha(ROOT/n) == v for n, v in review['bindings'].items())
    threads = defaultdict(list)
    for e in events:
        if e['provider'].startswith('3d6fa8d1') and e['opcode'] in (1, 2, 3, 4):
            fields, tail = decode(e, spec)
            assert fields['ProcessId'] == 11948
            threads[fields['TThreadId']].append(dict(qpc=e['qpc'], opcode=e['opcode'],
                fields=fields, uninterpreted_tail_hex=tail))
    assert sorted(threads) == read(HERE/'expanded_targets01.json')['lifecycle_tids']
    rows = []
    for tid, records in sorted(threads.items()):
        assert [r['opcode'] for r in records] == [3, 4]
        before, after = records
        assert before['qpc'] < after['qpc']
        for key in ('Win32StartAddr', 'TebBase', 'UserStackBase', 'UserStackLimit'):
            assert before['fields'][key] == after['fields'][key]
        entry = module_at(before['fields']['Win32StartAddr'], symbols['modules'])
        # Check both target-process image rundown endpoints for this exact range.
        image_endpoints = []
        if entry['module']:
            for e in events:
                if not e['provider'].startswith('2cb15d1d'): continue
                b = base64.b64decode(e['payload'])
                base, size, pid = struct.unpack_from('<QQI', b)
                if pid == 11948 and base <= entry['address'] < base+size:
                    image_endpoints.append(dict(opcode=e['opcode'], qpc=e['qpc'], base=base, size=size))
            assert sorted(v['opcode'] for v in image_endpoints) == [3, 4]
            assert len({(v['base'], v['size']) for v in image_endpoints}) == 1
        witnesses = [v for v in review['individual_examples'] if v['tid'] == tid]
        assert all(before['qpc'] <= v['qpc'] <= after['qpc'] and v['individual_witness_usable'] for v in witnesses)
        rows.append(dict(tid=tid, original_named_role=named.get(tid),
            entry=entry, rundown=records, image_rundown=image_endpoints,
            individual_CPU_witnesses=[{k:v[k] for k in ('qpc', 'ip', 'root_complete', 'ip_in_linked_stack', 'nonprocess')} for v in witnesses],
            creation_time_reference_available=tid in named, business_function=None, GIL_owner_identified=False))
    result = dict(target_pid=11948, scope='Old CPU-trace thread entry/library identity only; no new target or capture.',
        schema_computed_record_bytes=struct.calcsize(spec[0]), schema_extra_tail_not_interpreted=True,
        retained_threads=len(rows), entry_module_counts=dict(Counter(v['entry']['module'] for v in rows)), threads=rows,
        limits=['A Win32 entry inside a module identifies the entry address, not the current business task or private function.',
            'Generic CRT/Qt/system entries stay generic. No Python caller is inferred for a native worker.',
            'Rundown endpoints are not creation timestamps; no CPUcounter qualification or unseen-lifetime guarantee is added.',
            'This PID11948 cannot identify PID17752 allocation waiters or PID23008/14620 CPU-account threads, even when TIDs coincide.',
            'Thread existence/count is not concurrency, oversubscription, CPU time, GIL ownership or a performance contribution.',
            'Original stack/3%/1% failures remain failed. Missing CPU samples do not establish idleness.'],
        bindings={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__), HERE/'thread_start_schema01.json',
            HERE/'read_thread_schema01.ps1', HERE/'expanded_cpu_review01.json', HERE/'expanded_targets01.json', HERE/'expanded_review_plan01.json', fixture_path)},
        new_capture=False, primary_root_identified=False, field_fix_verified=False)
    with (HERE/'thread_entries01.json').open('x') as f: json.dump(result, f, indent=2)
    print(json.dumps(dict(threads=len(rows), entry_modules=result['entry_module_counts']), indent=2))
