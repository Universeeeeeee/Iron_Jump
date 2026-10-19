"""Cross-check published pairs against raw scheduler payloads, not just JSON flags."""
import base64
import bisect
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

if __name__ == '__main__':
    summary_path = HERE/'qt_label_wait_summary01.json'; s = read(summary_path)
    queue_path = HERE/'qt_wait_queue_bounds01.json'; queue = read(queue_path)
    for d in (s, queue): assert all(sha(ROOT/n) == v for n,v in d['bindings'].items())
    full = read(ROOT/s['raw_manifest']['raw_path'])
    assert all(sha(ROOT/n) == v for n,v in full['bindings'].items())
    assert not s['direct_historical_owner_identified'] and not s['primary_root_identified']
    assert not s['field_fix_verified'] and not queue['old_acceptance_upgraded']
    selected = s['GUI_QLatch_waits']+s['consumer_GIL_waits_participating']
    out, incoming, ready = set(), defaultdict(list), defaultdict(list)
    schedule = ROOT/'experiments/native_stack_capture/runs/gil_contenders01/schedule01.jsonl.gz'
    with gzip.open(schedule, 'rt') as f:
        for line in f:
            e = json.loads(line); b = base64.b64decode(e['payload'])
            if e['opcode'] == 36:
                new, old = struct.unpack_from('<II', b)
                if b[14] == 5: out.add((e['qpc'], old))
                if new in (20420,5376): incoming[new].append(e['qpc'])
            elif e['opcode'] == 50:
                tid = struct.unpack_from('<I', b)[0]
                if tid in (20420,5376): ready[tid].append(e['qpc'])
    for row in selected:
        tid = row['tid']; a, r, b = [row[k] for k in ('out_qpc','ready_qpc','in_qpc')]
        assert (a,tid) in out and a < r <= b
        assert incoming[tid][bisect.bisect_right(incoming[tid],a)] == b
        assert ready[tid][bisect.bisect_right(ready[tid],a)] == r
        source = full['GUI_QLatch_waits' if tid == 20420 else 'consumer_GIL_waits'][row['source_index']]
        assert all(source[k] == row[k] for k in ('tid','out_qpc','ready_qpc','in_qpc'))
        frames = source['frames']
        assert hashlib.sha256(json.dumps(frames,sort_keys=True,separators=(',',':')).encode()).hexdigest() == row['full_frames_canonical_json_sha256']
        assert frames[-1]['symbol'] == 'RtlUserThreadStart' and frames[-1]['pdb_matched']
        required = [('Qt6Core.dll','QLatch::waitInternal'),('Qt6Widgets.dll','QLabel::paintEvent')] if tid == 20420 else [('python311.dll','take_gil')]
        assert all(any(v['module']==module and v['symbol']==name and v['pdb_matched'] for v in frames) for module,name in required)
    guis = {v['source_index']:v for v in s['GUI_QLatch_waits']}
    consumers = {v['source_index']:v for v in s['consumer_GIL_waits_participating']}
    assert len(queue['pairs']) == len(s['guarded_simultaneous_waits'])
    for pair, workload in zip(s['guarded_simultaneous_waits'],queue['pairs']):
        a = guis[pair['GUI_wait_source_index']]; b = consumers[pair['consumer_wait_source_index']]
        assert pair['qpc_bounds'] == [max(a['out_qpc'],b['out_qpc'])+1000,min(a['ready_qpc'],b['ready_qpc'])-1000]
        assert pair['qpc_bounds'][0] <= pair['qpc_bounds'][1] and workload['available']
        assert workload['before']['read_end_upper_ns'] <= workload['full_host_ns_envelope'][0]
        assert workload['after']['row'][0] >= workload['full_host_ns_envelope'][1]
        assert workload['unfinished_batch_prefix_lag_lower_bound'] == max(0,workload['before']['row'][5]-workload['after']['row'][1])
    result = dict(raw_scheduler_pairs_crosschecked=len(selected), guarded_intersections=len(s['guarded_simultaneous_waits']),
        prefix_read_brackets_crosschecked=len(queue['pairs']), all_six_original_points_remain_without_GUI_latch=all(not v['GUI_latch_wait_indices'] for v in s['six_existing_batch_pending_points']),
        source_result_sha256={p.name:sha(p) for p in (summary_path,queue_path)}, verifier_sha256=sha(Path(__file__)),
        old_acceptance_upgraded=False, direct_owner_snapshot=False, root_cause_or_fix_complete=False)
    with (HERE/'qt_label_verification01.json').open('x') as f: json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
