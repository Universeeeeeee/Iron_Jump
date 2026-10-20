"""Frozen replicated cold-first process boundary decision."""
def decide(rows,plan):
    g=plan['decision'];quality=all(v['complete'] and v['boot_qualified'] and v['input_lateness_ms']<=g['input_lateness_max_ms'] for v in rows.values())
    originals=[rows[n] for n in plan['original_cases']];processes=[rows[n] for n in plan['process_cases']]
    original_severe=[v['observed_queue_lower']>=g['severe_queue_lower'] and v['scheduled_max_ms']>=g['severe_latency_ms'] for v in originals]
    process_bounded=[v['queue_upper']<=g['process_queue_upper'] and v['scheduled_max_ms']<=g['process_latency_ms'] for v in processes]
    support=quality and all(original_severe) and all(process_bounded)
    reject=quality and any(v['observed_queue_lower']>=g['severe_queue_lower'] and v['scheduled_max_ms']>=g['severe_latency_ms'] for v in processes)
    reason='support_process_candidate' if support else 'reject_process_candidate' if reject else 'cold_original_severity_not_reproduced' if quality and not all(original_severe) else 'protocol_quality_failed'
    return dict(advance_to_field=support,reason=reason,quality=quality,original_severe=original_severe,process_bounded=process_bounded,formal_fix_verified=False,field_fix_verified=False)
