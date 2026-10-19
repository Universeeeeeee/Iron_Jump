"""Publish all paired timing references, retaining redundant full chains locally."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))


def compact(row, index):
    return dict(source_index=index, **{k:row[k] for k in ('tid', 'out_qpc', 'ready_qpc', 'in_qpc')},
        full_frames_canonical_json_sha256=hashlib.sha256(json.dumps(row['frames'], sort_keys=True,
            separators=(',', ':')).encode()).hexdigest())


if __name__ == '__main__':
    preservation = read(HERE/'qt_label_raw_preservation01.json')
    raw_path = ROOT/preservation['raw_path']
    assert raw_path.stat().st_size == preservation['bytes'] and sha(raw_path) == preservation['sha256']
    raw = read(raw_path)
    assert all(sha(ROOT/n) == v for n,v in raw['bindings'].items())
    consumer_indices = sorted({v['consumer_wait_index'] for v in raw['guarded_simultaneous_waits']})
    first_by_boundary = {}
    for index in consumer_indices:
        row = raw['consumer_GIL_waits'][index]
        boundary = tuple(sorted({f['symbol'] for f in row['frames'] if f['symbol'] in
            ('PyEval_RestoreThread', 'PyGILState_Ensure')}))
        assert boundary
        first_by_boundary.setdefault(boundary, dict(source_index=index, **row))
    result = {k:v for k,v in raw.items() if k not in ('GUI_QLatch_waits', 'consumer_GIL_waits', 'guarded_simultaneous_waits', 'bindings')}
    result.update(raw_manifest=preservation,
        GUI_QLatch_waits=[compact(v,i) for i,v in enumerate(raw['GUI_QLatch_waits'])],
        consumer_GIL_waits_participating=[compact(raw['consumer_GIL_waits'][i],i) for i in consumer_indices],
        first_GUI_full_chain=raw['GUI_QLatch_waits'][0] if raw['GUI_QLatch_waits'] else None,
        first_overlapping_consumer_full_chain_per_boundary=list(first_by_boundary.values()),
        guarded_simultaneous_waits=[dict(GUI_wait_source_index=v['gui_wait_index'],
            consumer_wait_source_index=v['consumer_wait_index'], qpc_bounds=v['guarded_common_before_Ready_qpc'])
            for v in raw['guarded_simultaneous_waits']],
        qualified_GUI_wait_count=len(raw['GUI_QLatch_waits']), qualified_consumer_wait_count=len(raw['consumer_GIL_waits']),
        full_consumer_chains_kept_locally=True, frames_digest_format='UTF-8 json.dumps(sort_keys=True,separators=(comma,colon))',
        selection='All timing references for every qualified GUI latch wait and every guarded intersection. Full-chain examples are the first by observed order per consumer GIL boundary, not selected for longest waits.',
        bindings={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__), HERE/'qt_label_wait_review.py',
            HERE/'qt_label_raw_preservation01.json', raw_path, HERE/'label_boundary01.json', HERE/'error_api01.json']})
    with (HERE/'qt_label_wait_summary01.json').open('x') as f: json.dump(result, f, indent=2)
    print(json.dumps(dict(GUI_waits=result['qualified_GUI_wait_count'],
        all_consumer_waits=result['qualified_consumer_wait_count'], participating_consumers=len(consumer_indices),
        guarded_pairs=len(result['guarded_simultaneous_waits']),
        consumer_boundaries=[list(v) for v in first_by_boundary]), indent=2))
