"""Sequential AB/BA orchestration and diagnostics, separate from scored runs."""
from collections import Counter
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

from experiment import (HERE, ROOT, APP, VARIANTS, Decoder, PreparedDevice, WalkingProcessor,
                        OvergroundRunningProcessor, RetirementShadow, assert_equal, config_for,
                        correctness, digest, dump, observations, pipeline, recorded, synthetic,
                        verify_sources, feed_quality)
import numpy as np


def diagnostic(name, mode, layout, frames, meta=None):
    q, s = pipeline(mode, layout, frames, 'baseline', meta)
    timings = {key: [] for key in ('decode', 'runtime', 'filter', 'processor', 'consumer')}
    activity = Counter()
    original_observe = q._runtime.observe
    original_feed = s._frame_filter.feed
    original_process = s.processor.process
    shadow = RetirementShadow(layout)
    spatial = s.processor._clusters if mode == 'walk' else s.processor._groups
    retirement_spatial_upper_ns = 0
    idle_reference = __import__('candidates').idle_eligible

    def wrapped_observe(f):
        start = time.perf_counter_ns()
        result = original_observe(f)
        timings['runtime'].append(time.perf_counter_ns()-start)
        return result

    def wrapped_feed(f):
        activity['settled_input'] += f.contact_bits == s._frame_filter._settled_bits
        start = time.perf_counter_ns()
        result = original_feed(f)
        timings['filter'].append(time.perf_counter_ns()-start)
        return result

    def wrapped_process(f, observation=None, *, masked_contact=False):
        nonlocal retirement_spatial_upper_ns
        activity['formal_calls'] += 1
        activity['idle_eligible'] += idle_reference(s.processor, f, observation, masked_contact)
        activity['with_active_contact'] += bool(s.processor.active)
        activity['with_narrow_candidate'] += bool(s.processor._narrow_candidates)
        start = time.perf_counter_ns()
        result = original_process(f, observation, masked_contact=masked_contact)
        timings['processor'].append(time.perf_counter_ns()-start)
        shadow.observe(s.processor, f)
        if shadow.retired:
            # Deliberately labelled an upper bound: includes ALL cluster work,
            # not an invented sum of per-segment CPU savings.
            start = time.perf_counter_ns(); spatial(f.contact_bits)
            retirement_spatial_upper_ns += time.perf_counter_ns()-start
        return result

    q._runtime.observe = wrapped_observe
    s._frame_filter.feed = wrapped_feed
    s.processor.process = wrapped_process
    decoder = Decoder(layout)
    for f in frames:
        start = time.perf_counter_ns(); bits = decoder.decode(f.wire_payload)
        timings['decode'].append(time.perf_counter_ns()-start)
        start = time.perf_counter_ns(); feed_quality(q, replace(f, contact_bits=bits))
        timings['consumer'].append(time.perf_counter_ns()-start)
    s.halt()
    assert activity['formal_calls'] == len(frames), (name, 'partial formal coverage', activity)
    assert s.processor.last_sample == frames[-1].sample_index
    assert s.processor.finished_reason is None, (name, s.processor.finished_reason)
    result = observations(name, layout, frames)
    result.update(mode=mode, activity=dict(activity),
        stage_wall_us={k: {'p50': float(np.percentile(v, 50))/1000,
                          'p95': float(np.percentile(v, 95))/1000,
                          'p99': float(np.percentile(v, 99))/1000,
                          'max': max(v)/1000, 'sum': sum(v)/1000, 'calls': len(v)}
                       for k, v in timings.items() if v},
        retirement={'eligible_segment_samples': shadow.eligible_segments,
                    'total_segment_samples': shadow.frame_segments,
                    'events': shadow.events,
                    'all_spatial_wall_upper_bound_ns': retirement_spatial_upper_ns,
                    'actual_retirement_enabled': False,
                    'limitation': 'Spatial upper bound is perturbed wall time, not incremental retired-segment CPU savings.'},
        limitation='Diagnostic wrappers and retirement shadow add overhead; nested stages must not be summed; not a scored performance run.')
    return result


def run_benchmark(case, variant, target, label):
    folder = HERE/'benchmarks'; folder.mkdir(exist_ok=True)
    out = folder/(label+'.json')
    cmd = [sys.executable, str(HERE/'experiment.py'), 'bench', '--case', case,
           '--variant', variant, '--target', target, '--output', str(out)]
    with out.with_suffix('.stdout').open('w') as stdout, out.with_suffix('.stderr').open('w') as stderr:
        subprocess.run(cmd, stdout=stdout, stderr=stderr, check=True, cwd=ROOT)
    return json.loads(out.read_text())


def paired(case, variant, target):
    results = []; pairs = []
    for pair, order in enumerate((('baseline', variant), (variant, 'baseline'),
                                 ('baseline', variant), (variant, 'baseline'))):
        rows = {}
        for index, name in enumerate(order):
            label = f'{target}_{case}_{variant}_{pair}_{index}_{name}'
            row = run_benchmark(case, name, target, label)
            rows[name] = row; results.append(row)
        base, cand = rows['baseline'], rows[variant]
        if target == 'pipeline':
            assert base['report_sha256'] == cand['report_sha256'], (case, variant, pair, 'report')
            assert base['accepted_frames'] == cand['accepted_frames']
        pairs.append({'pair': pair, 'order': list(order),
                      'cpu_reduction': 1-cand['cpu_ns']/base['cpu_ns'],
                      'wall_reduction': 1-cand['wall_ns']/base['wall_ns']})
    values = [p['cpu_reduction'] for p in pairs]
    result = {'case': case, 'variant': variant, 'target': target, 'runs': results, 'pairs': pairs,
              'median_cpu_reduction': statistics.median(values),
              'positive_pairs': sum(x>0 for x in values),
              'environment': 'local macOS, unpaced CPU experiment, no GUI/ETW/hardware'}
    print(json.dumps({k: result[k] for k in ('case','variant','target','median_cpu_reduction','positive_pairs')}), flush=True)
    return result


def shadow_adversarial():
    """Exercise reentry and direction/quality invalidation with concrete states."""
    from experiment import make_frame
    from types import SimpleNamespace
    layout, _ = synthetic('empty', 1)
    def owner(direction=1):
        return SimpleNamespace(direction=direction, positions=layout.positions_m,
            active=[], _narrow_candidates=[], _ownership_groups=[], _local_regions=[],
            _recovering=False, config=SimpleNamespace(release_ms=20),
            contacts=[SimpleNamespace(confirmed=True, touch_known=True, low=300, high=320)])
    rows = []
    for trigger in ('return', 'reverse', 'invalid', 'unknown_direction', 'pending', 'gap', 'stream'):
        shadow=RetirementShadow(layout); p=owner()
        for n in range(25): shadow.observe(p, make_frame(layout,n))
        assert 0 in shadow.retired
        f = make_frame(layout,25, [(10,20)] if trigger=='return' else [])
        if trigger=='reverse':p.direction=-1
        if trigger=='unknown_direction':p.direction=0
        if trigger=='invalid': f=replace(f,valid_bits=bytes(layout.bit_count))
        if trigger=='pending':p.active=[SimpleNamespace(low=10,high=20)]
        if trigger=='gap':f=replace(f,sample_index=27)
        if trigger=='stream':f=replace(f,stream_id='changed')
        shadow.observe(p,f)
        assert 0 not in shadow.retired, trigger
        rows.append({'trigger':trigger,'revoked_on_trigger_sample':True,'events':shadow.events})
    return rows


def main():
    action = sys.argv[1]
    if action == 'one':
        experiment = sys.argv[2]
        specs = {'E1': [('decode_full','decode'),('decode_segments','decode')],
                 'E2a': [('runtime','runtime')], 'E2b': [('idle','processor')],
                 'E3': [('clusters','clusters')]}
        cases=('empty','sparse','cross','plateau','stress',
               'field_run_20261015_02','field_walk_full_02')
        stages=[]; pipelines=[]
        for variant,target in specs[experiment]:
            for case in cases:
                stages.append(paired(case,variant,target))
                dump(HERE/f'{experiment}_stage.json',{'results':stages,'complete':False})
        dump(HERE/f'{experiment}_stage.json',{'results':stages,'complete':True})
        variants=[variant for variant,_ in specs[experiment]]
        segmented_wins=None
        if experiment=='E1':
            def candidate_cpu(variant,case):
                r=next(r for r in stages if r['variant']==variant and r['case']==case)
                return statistics.median(x['cpu_ns'] for x in r['runs'] if x['variant']==variant)
            segmented_wins=(all(candidate_cpu('decode_segments',c)<=.9*candidate_cpu('decode_full',c)
                                for c in ('sparse','cross'))
                            and all(candidate_cpu('decode_segments',c)<=1.05*candidate_cpu('decode_full',c)
                                    for c in cases if c not in ('sparse','cross')))
            variants=['decode_segments' if segmented_wins else 'decode_full']
        for variant in variants:
            admitted=any(r['variant']==variant and r['median_cpu_reduction']>=.2
                         and r['positive_pairs']>=3 for r in stages)
            if admitted:
                for case in cases:
                    pipelines.append(paired(case,variant,'pipeline'))
                    dump(HERE/f'{experiment}_pipeline.json',{'results':pipelines,'complete':False})
        dump(HERE/f'{experiment}_pipeline.json',{'results':pipelines,'complete':True,
             'selected_variants':variants,'segmented_decoder_beats_simple_cache':segmented_wins})
        return
    if action == 'diagnostic':
        rows=[]
        for name in ('empty','sparse','cross','plateau','stress'):
            layout,frames=synthetic(name)
            row=diagnostic(name,'run',layout,frames);rows.append(row)
            print(name, row['activity'], flush=True)
        for name,mode in (('field_run_20261015_02','run'),('field_walk_full_02','walk')):
            layout,frames,meta=recorded(name)
            rows.append(diagnostic(name,mode,layout,frames,meta));print(name,flush=True)
        dump(HERE/'diagnostic.json',{'runs':rows,'shadow_adversarial':shadow_adversarial(),
                                    'source_verification':verify_sources()})
    elif action == 'performance':
        rows=[]
        for variant,target in (('decode_full','decode'),('decode_segments','decode'),
                               ('runtime','runtime'),('idle','processor'),('clusters','clusters')):
            for name in ('empty','sparse','cross','plateau','stress',
                         'field_run_20261015_02','field_walk_full_02'):
                rows.append(paired(name,variant,target))
                dump(HERE/'stage_benchmarks.json',{'results':rows,'complete':False})
        dump(HERE/'stage_benchmarks.json',{'results':rows,'complete':True})
    elif action == 'pipeline':
        stages=json.loads((HERE/'stage_benchmarks.json').read_text())['results']
        stage_map={(r['variant'],r['case']):r for r in stages}
        def median_candidate(variant,case):
            return statistics.median(x['cpu_ns'] for x in stage_map[variant,case]['runs']
                                     if x['variant']==variant)
        segmented_wins=all(median_candidate('decode_segments',case)
                          <=.90*median_candidate('decode_full',case) for case in ('sparse','cross'))
        segmented_wins &= all(median_candidate('decode_segments',case)
                             <=1.05*median_candidate('decode_full',case)
                             for case in ('empty','plateau','stress',
                                          'field_run_20261015_02','field_walk_full_02'))
        variants=[]
        for variant in ('decode_full','decode_segments','runtime','idle','clusters'):
            s=[r for r in stages if r['variant']==variant]
            if any(r['median_cpu_reduction']>=.20 and r['positive_pairs']>=3 for r in s):
                if variant!='decode_segments' or segmented_wins:
                    variants.append(variant)
        rows=[]
        for variant in variants:
            for name in ('empty','sparse','cross','plateau','stress',
                         'field_run_20261015_02','field_walk_full_02'):
                rows.append(paired(name,variant,'pipeline'))
                dump(HERE/'pipeline_benchmarks.json',{'results':rows,'complete':False})
        dump(HERE/'pipeline_benchmarks.json',{'results':rows,'complete':True,'stage_eligible':variants,
                                             'segmented_decoder_beats_simple_cache':segmented_wins})
    elif action == 'combined':
        singles=json.loads((HERE/'pipeline_benchmarks.json').read_text())['results']
        selected=[]
        for variant in ('decode_full','decode_segments','runtime','idle','clusters'):
            rs=[r for r in singles if r['variant']==variant]
            if (rs and any(r['median_cpu_reduction']>=.05 and r['positive_pairs']>=3 for r in rs)
                    and all(r['median_cpu_reduction']>=-.05 for r in rs)):
                selected.append(variant)
        if not selected:
            dump(HERE/'combined_benchmarks.json',{'selected':[],'reason':'No single candidate passed CPU gates'})
            return
        os.environ['IRON_SPARSE_FEATURES']=','.join(selected)
        dump(HERE/'combined_features.json',{'selected':selected,
             'gate':'At least one intended case >=5% pipeline CPU saving in >=3/4 pairs; no case median regression >5%.'})
        rows=[]
        for name,mode in (('field_run_20261015_02','run'),('field_walk_full_02','walk')):
            layout,frames,meta=recorded(name)
            row=correctness(name,layout,frames,mode,'combined',meta)
            rows.append(row);print(row,flush=True)
        dump(HERE/'combined_correctness.json',{'results':rows})
        timings=[paired(name,'combined','pipeline') for name in
                 ('empty','sparse','cross','plateau','stress','field_run_20261015_02','field_walk_full_02')]
        dump(HERE/'combined_benchmarks.json',{'results':timings})
    else:
        raise SystemExit('diagnostic | performance | pipeline | combined')


if __name__=='__main__':
    try:
        main()
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
