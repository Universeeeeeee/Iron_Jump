"""Recheck the six existing witnesses against raw stacks and ReadyThread events."""
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
REVIEWS = NATIVE / 'field_reviews'
spec = importlib.util.spec_from_file_location('stack_analysis', NATIVE / 'analyze.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    paths = [REVIEWS / '20261017_field_wait01/round02/batch_wait_witnesses01.json',
             REVIEWS / 'gil_contenders01/joined01.json',
             NATIVE / 'runs/gil_contenders01/schedule01.jsonl.gz',
             NATIVE / 'runs/field_wait01_round02/split01/17752/decoded/events.jsonl',
             NATIVE / 'runs/field_wait01_round02/split01/17752/symbols03.json',
             ROOT / 'experiments/single_usb_human_etw/runs/20261017_214905_5c874d97_walk_off/capture/measurement.json']
    witness, joined, symbols, measurement = (a.read(paths[i]) for i in (0, 1, 4, 5))
    assert len(witness['witnesses']) == 6 and witness['pid'] == measurement['pid'] == 17752
    assert witness['tid'] == measurement['threads']['consumer'] == 5376
    assert sha(paths[3]) == symbols['events_sha256']
    assert all(sha(ROOT / name) == value for name, value in joined['input_sha256'].items())
    manifest = a.read(paths[5].parent.parent / 'original_manifest.json')
    assert sha(paths[5]) == manifest['capture\\measurement.json']['sha256']
    switches, ready = set(), []
    with gzip.open(paths[2], 'rt') as source:
        for line in source:
            e = json.loads(line)
            d = base64.b64decode(e['payload'])
            if e['opcode'] == 36:
                new, old = struct.unpack_from('<II', d)
                switches.add((e['qpc'], new, old, d[14]))
            elif e['opcode'] == 50 and struct.unpack_from('<I', d)[0] == 5376:
                ready.append(e['qpc'])
    wanted = {w['switch_in_qpc'] for w in witness['witnesses']}
    stacks = defaultdict(list)
    with paths[3].open() as source:
        for line in source:
            e = json.loads(line)
            if not e['provider'].startswith('def2fe46'):
                continue
            d = base64.b64decode(e['payload'])
            q, pid, tid = struct.unpack_from('<QII', d)
            if q in wanted and tid == 5376:
                assert pid == 17752
                stacks[q].append(struct.unpack_from('<' + 'Q' * ((len(d) - 16) // 8), d, 16))
    verified = []
    for w in witness['witnesses']:
        row = w['queue_snapshot']
        assert row in measurement['queue_samples']
        assert row[3] > 100 and row[8] == row[12] == 20 and row[9] == 'batch'
        start, finish = w['switch_out_qpc'], w['switch_in_qpc']
        assert any(q == start and old == 5376 and state == 5 for q, new, old, state in switches)
        assert any(q == finish and new == 5376 for q, new, old, state in switches)
        wake = ready[bisect.bisect_right(ready, start)]
        assert start < wake <= finish
        mapping = witness['mapping']
        lower = start * 100 + mapping['host_ns_offset_upper']
        upper = wake * 100 + mapping['host_ns_offset_lower']
        margin = min(row[0] - lower, upper - row[0])
        assert margin >= 100000, 'Must be before ReadyThread, not merely before switch-in'
        info = a.stack_info(stacks[finish], symbols['addresses'])
        assert info['root_complete'] and not info['ambiguous'] and 'gil_wait_chain' in info['families']
        names = [f['symbol'] for f in info['frames']]
        assert all(f.get('pdb_matched') for f in info['frames']
                   if f['symbol'] in ('take_gil', 'PyEval_RestoreThread', 'PyGILState_Ensure', 'NtWaitForSingleObject'))
        numpy_rvas = [f['rva'] for f in info['frames'] if 'multiarray' in (f['module'] or '')]
        family = ('PySide callback GIL entry' if 'PyGILState_Ensure' in names else
                  'NumPy reduction GIL return' if 0x173161 in numpy_rvas else
                  'NumPy unnamed GIL return')
        verified.append(dict(formal_s=w['host_formal_s'], pending=row[3],
            batch=row[10:13], switch_out_qpc=start, ready_qpc=wake,
            switch_in_qpc=finish, conservative_wait_guard_margin_us=margin / 1000,
            family=family, numpy_rvas=numpy_rvas))
    chain_path = ROOT / 'experiments/walk_compute_offline_diagnosis/chain_summary01.json'
    paths.append(chain_path)
    chain = a.read(chain_path)
    costs = [dict(case=t['case'], contact_core=t['phases']['contact_core']['wall_us_per_input'],
                  initial_empty=t['phases']['initial_empty']['wall_us_per_input']) for t in chain['trials']]
    delta = (costs[1]['contact_core']['median'] / costs[2]['contact_core']['median'] - 1) * 100
    for path in [REVIEWS / '20261017_field_wait01/round02/acceptance.json',
                 REVIEWS / '20261017_field_cpu01/round01/acceptance.json']:
        assert not a.read(path)['measurement_acceptance_pass']
        paths.append(path)
    result = dict(verified_existing_witnesses=verified, original_chain_costs=costs,
        ON2_vs_ON3_contact_core_median_wall_difference_pct=delta,
        native_acceptance_unchanged_false=True,
        input_sha256={str(p.relative_to(ROOT)): sha(p) for p in paths},
        scope='Offline consistency/identity and before-Ready witness validation only. No new recording, replay benchmark, optimization comparison or time-share attribution.')
    with Path(__file__).with_name('verification01.json').open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    print('Verified six complete GIL chains inside batch/pending and before ReadyThread; historical median difference:', delta)


if __name__ == '__main__':
    main()
