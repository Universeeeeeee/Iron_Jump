"""Posthoc review of every window in two completed, immutable cohorts; no launches."""
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def summarize(r):
    c, m = r['consumer'], r['model']
    calls = m['calls']
    assert r['complete'] and not r['errors'] and not r['worker_alive']
    assert r['full_original_chain_exact'] and r['process_accounting']['accounting_pass']
    assert len(calls) == 220 and [v['ordinal'] for v in calls] == list(range(220))
    assert m['ready_ns'] <= c['begin_ns'] and m['begin_ns'] >= m['ready_ns']
    tail = calls[125:220]
    assert all(v['begin_ns'] >= c['end_ns'] for v in tail)
    # Same ordinal subset in all 16 windows. Chosen posthoc, not independent trials.
    return dict(
        variant=r['variant'],
        ready_to_consumer_ms=(c['begin_ns']-m['ready_ns'])/1e6,
        consumer_wall_ms=(c['end_ns']-c['begin_ns'])/1e6,
        consumer_cpu_ms=c['thread_cpu_ns']/1e6,
        tail_calls=95,
        tail_median_ms=statistics.median((v['end_ns']-v['begin_ns'])/1e6 for v in tail),
        tail_mean_ms=statistics.mean((v['end_ns']-v['begin_ns'])/1e6 for v in tail),
        model_close_ms=(m['close_end_ns']-m['close_begin_ns'])/1e6,
        process_cpu_ms=r['process_accounting']['process_cpu_ns']/1e6,
        process_cycles=r['process_accounting']['process_cycles'],
    )


if __name__ == '__main__':
    cohorts = {}; bindings = {}; identities = []; tail_keys = []
    for name in ('fixed_overlap_comparison', 'cv2_parallel_candidate/performance'):
        folder = ROOT/'experiments'/name/'runs/evidence01'
        manifest = read(folder/'manifest.json')
        assert all(sha(folder/n) == v for n,v in manifest.items())
        plan = read(folder/'plan01.json'); status = read(folder/'runs/status.json')
        assert status['complete'] and not status['errors'] and len(plan['cases']) == 8
        rows = {}
        for case in plan['cases']:
            path = folder/'runs'/case/'result.json'; r = read(path)
            identities.append((r['frame_evidence'],r['model_result_sha256'],r['report_sha256']))
            tail_keys.append([(v['ordinal'],v['frame_id'],v['logical_ms']) for v in r['model']['calls'][125:220]])
            rows[case] = summarize(r)
            bindings[f'{name}/{case}'] = sha(path)
        cohorts[name] = rows
    assert all(v == identities[0] for v in identities)
    assert all(v == tail_keys[0] for v in tail_keys)
    result = dict(cohorts=cohorts, all_16_work_identities_equal=True,
        tail_ordinals=[125,219], tail_after_consumer_in_all_windows=True,
        source_bindings=bindings, analyzer_sha256=sha(Path(__file__)),
        exploratory=True, causal_attribution=False, field_fix_verified=False,
        limits=[
            'Ready-to-consumer is a wall-time proxy for the common historical-frame preparation, including coordinator wakeup and accounting; no preparation CPU counters exist.',
            'The model is ready but no infer_bgr call is released during historical-frame preparation. Idle native model threads can still exist.',
            'Common tail ordinals were selected after inspecting all windows. The95 calls are dependent repeated work, not95 independent replicates.',
            'Different cohorts, serial/concurrent schedules and OpenCV variants remain separate. No cross-cohort subtraction or causal effect estimate.',
            'Process cycles and CPU time do not identify effective CPU frequency, instructions, temperature, external load or waiting shares.',
        ])
    with (HERE/'result01.json').open('x') as f: json.dump(result,f,indent=2)
    print(json.dumps(cohorts,indent=2))
