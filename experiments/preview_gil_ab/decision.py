"""Frozen severe-baseline gate; never substitute a fast-state improvement."""


def decide(rows,plan):
    expected=[v['id'] for v in plan['cases']]
    assert set(rows)==set(expected)
    gates=plan['decision'];pairs=[];quality=True
    for pair in plan['pairs']:
        a,b=rows[pair['original']],rows[pair['bridge']]
        for row in (a,b):
            quality=quality and row.get('complete',False) and row.get('semantics_pass',False) and row.get('native_SDK_pass',False)
            quality=quality and row.get('input_lateness_ms',float('inf'))<=gates['input_lateness_max_ms']
        severe=a.get('observed_queue_lower',-1)>=gates['severe_observed_queue_at_least'] and a.get('scheduled_max_ms',-1)>=gates['severe_scheduled_latency_at_least_ms']
        bounded=b.get('queue_upper',float('inf'))<=gates['candidate_queue_upper_max'] and b.get('scheduled_max_ms',float('inf'))<=gates['candidate_scheduled_latency_max_ms']
        improvement=severe and b['scheduled_max_ms']<=a['scheduled_max_ms']*(1-gates['minimum_severe_pair_latency_reduction'])
        pairs.append(dict(original=pair['original'],bridge=pair['bridge'],severe_original=severe,candidate_absolute_bounds_pass=bounded,severe_pair_improved=improvement))
    replicated=sum(p['severe_original'] for p in pairs)>=gates['minimum_severe_original_windows']
    advance=quality and replicated and all(p['candidate_absolute_bounds_pass'] for p in pairs) and all(p['severe_pair_improved'] for p in pairs if p['severe_original'])
    reason='qualified_severe_symptom_improvement' if advance else 'protocol_or_input_quality_failed' if not quality else 'severe_baseline_not_reproduced' if not replicated else 'candidate_did_not_meet_frozen_benefit'
    return dict(protocol_quality_pass=quality,severe_baseline_reproduced=replicated,pairs=pairs,advance=advance,reason=reason,
        fast_state_benefit_substituted=False,root_cause_share_identified=False,formal_fix_verified=False)
