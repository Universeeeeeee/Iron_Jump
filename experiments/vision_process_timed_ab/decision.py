"""Frozen A/A reliability and severe-backlog process-boundary decision."""
import math
import statistics

def relative_range(values):
    if not values or min(values)<=0:raise ValueError('Positive values required')
    return max(values)/min(values)-1

def decide(rows,plan):
    aa=[rows[name] for name in plan['aa_cases']];g=plan['decision']
    aa_ranges={key:relative_range([v[key] for v in aa]) for key in ('scheduled_max_ms','observed_queue_lower')}
    aa_ranges.update(video=relative_range([v['work']['video'] for v in aa]),inferences=relative_range([v['work']['inferences'] for v in aa]))
    aa_quality=all(v['complete'] and v['input_lateness_ms']<=g['input_lateness_max_ms'] for v in aa)
    aa_stable=aa_quality and all(value<=g['aa_relative_range_max'] for value in aa_ranges.values())
    pairs=[];protocol=aa_quality
    for pair in plan['pairs']:
        original,process=rows[pair['original']],rows[pair['process']]
        quality=all(v['complete'] and v['input_lateness_ms']<=g['input_lateness_max_ms'] for v in (original,process))
        quality=quality and original['context_comparable'] and process['context_comparable'];protocol=protocol and quality
        severe=original['observed_queue_lower']>=g['severe_observed_queue_at_least'] and original['scheduled_max_ms']>=g['severe_scheduled_latency_at_least_ms']
        bounded=process['queue_upper']<=g['candidate_queue_upper_max'] and process['scheduled_max_ms']<=g['candidate_scheduled_latency_max_ms']
        improved=severe and process['scheduled_max_ms']<=original['scheduled_max_ms']*(1-g['minimum_severe_pair_latency_reduction'])
        pairs.append(dict(**pair,quality=quality,severe_original=severe,process_absolute_bounds_pass=bounded,severe_pair_improved=improved))
    replicated=sum(v['severe_original'] for v in pairs)>=g['minimum_severe_original_windows']
    advance=protocol and aa_stable and replicated and all(v['process_absolute_bounds_pass'] for v in pairs) and all(v['severe_pair_improved'] for v in pairs if v['severe_original'])
    reason='qualified_severe_process_improvement' if advance else 'protocol_quality_failed' if not protocol else 'aa_variability_exceeds_gate' if not aa_stable else 'severe_baseline_not_reproduced' if not replicated else 'process_candidate_failed_bounds'
    return dict(advance=advance,reason=reason,protocol_quality_pass=protocol,aa_quality_pass=aa_quality,aa_stable=aa_stable,aa_relative_ranges=aa_ranges,
        severe_baseline_reproduced=replicated,pairs=pairs,quantitative_root_share_identified=False,field_fix_verified=False)
