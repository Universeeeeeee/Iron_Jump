"""Metric evidence from existing ownership groups; no tracking or publication."""

from engine.ground_source_review import ownership_record, assigned_sources

METRIC_POLICY = 'independent_boundaries_source_review_v2'


def group_release_evidence(groups, contact_id):
    group = next((g for g in groups if (ownership_record(g) or {}).get('owner_id') == contact_id), None)
    if group is None:
        return None
    recovery = ownership_record(group)
    assigned = assigned_sources(group)
    evidence = {'basis': 'conditional_group_clear', 'group_id': group['id'],
                'source_ids': sorted(assigned), 'rule_version': recovery['rule_version'],
                'metric_policy': METRIC_POLICY, 'start_sample': recovery['original_touch_sample'],
                'end_sample': group['occupancy_end_sample'],
                'valid_sample_intervals': [list(r) for r in group['valid_sample_intervals']],
                'closed_sample': group['tracking_ended_sample'], 'missing_reason': None}
    if group.get('source_decisions'):
        evidence['source_decisions'] = [dict(d) for d in group['source_decisions']]
    evidence['occupied_until_sample'] = group['last_sample'] + 1
    evidence['occupancy_valid'] = (
        assigned == {s['source_id'] for s in group['sources']}
        and group['valid_sample_intervals'] == [[recovery['original_touch_sample'], group['last_sample'] + 1]]
        and bool(group['observation_runs']) and all(r[3] for r in group['observation_runs']))
    if assigned != {s['source_id'] for s in group['sources']}:
        evidence['missing_reason'] = 'competing_source'
    elif (group['tracking_end_reason'] != 'reliable_clear' or group['occupancy_end_sample'] is None):
        evidence['missing_reason'] = 'lift_not_observed'
    elif (not evidence['occupancy_valid'] or group['last_sample'] + 1 != group['occupancy_end_sample']):
        evidence['missing_reason'] = 'incomplete_observation'
    return evidence


def metric(value=None, reason=None):
    return {"value": value, "valid": value is not None and reason is None,
            "missing_reason": reason if reason else ("not_observed" if value is None else None)}
