"""Reliable landing identities, independent of valid gait relationships."""
from copy import deepcopy

FOOTFALL_SCHEMA = 'walking-footfalls/1.0'

def validate_footfalls(summary):
    rows = summary['footfalls']
    events = active_touch_events(summary['event_publications'])
    expected = {(event['epoch'], event['contact_id']): event for event in events}
    if summary['recognized_steps'] != len(rows) or len(rows) != len(expected):
        raise ValueError('Recognized steps and active footfall records disagree')
    seen = set()
    for row in rows:
        key = (row['epoch'], row['contact_id'])
        if key in seen or key not in expected:
            raise ValueError('Duplicate or inactive footfall record')
        seen.add(key)
        if any(row[field] != expected[key][field] for field in
               ('event_id', 'touch_sample', 'published_sample')):
            raise ValueError('Footfall event provenance changed')
        if row['raw_landing_position_m'] != summary.get('landing_positions_m', {}).get(str(row['contact_id'])):
            raise ValueError('Footfall publication coordinate changed')

def active_touch_events(events):
    """Latest revision wins; a retraction removes the original landing."""
    latest = {}
    for event in events:
        key = (event['epoch'], event['contact_id'])
        if key not in latest or event.get('revision', 1) >= latest[key].get('revision', 1):
            latest[key] = event
    return sorted((event for event in latest.values() if event['active']),
                  key=lambda event: (event['touch_sample'], event['epoch'], event['contact_id']))

def footfall_records(summary):
    """Use publication-time coordinates; never invent a missing metric."""
    contacts = {(row.get('epoch', 0), row['id']): (index, row)
                for index, row in enumerate(summary['contacts'])}
    records = []
    for event in active_touch_events(summary.get('event_publications', [])):
        index, contact = contacts[(event['epoch'], event['contact_id'])]
        incoming = next(((i, step) for i, step in enumerate(summary['steps'])
                         if step['to_id'] == event['contact_id']), None)
        def relation_metric(name):
            value = incoming[1][name] if incoming else None
            return dict(value=value, valid=value is not None,
                        missing_reason=None if value is not None else
                        'no_valid_step_relationship' if incoming is None else 'position_not_observed')
        def contact_metric(name):
            value = contact.get(name, dict(value=None, valid=False, missing_reason='not_observed'))
            return {key: deepcopy(value.get(key)) for key in ('value', 'valid', 'missing_reason')}
        position = summary.get('landing_positions_m', {}).get(str(event['contact_id']))
        records.append(dict(event_id=event['event_id'], contact_id=event['contact_id'],
            epoch=event['epoch'], revision=event.get('revision', 1),
            touch_sample=event['touch_sample'], published_sample=event['published_sample'],
            sample_time_s=event['touch_sample'] / 1000, timestamp_s=contact['touch_s']['value'],
            raw_landing_position_m=position,
            raw_position_missing_reason=None if position is not None else 'publication_position_not_recorded',
            side=contact.get('side', 'unknown'),
            side_missing_reason=None if contact.get('side', 'unknown') != 'unknown' else 'anatomical_side_unknown',
            touch_s=contact_metric('touch_s'), lift_s=contact_metric('lift_s'),
            contact_s=contact_metric('contact_s'), centre_m=contact_metric('centre_m'),
            step_time_s=relation_metric('time_s'), step_length_m=relation_metric('length_m'),
            speed_m_s=relation_metric('speed_m_s'),
            step_refs=[i for i, step in enumerate(summary['steps'])
                       if event['contact_id'] in (step['from_id'], step['to_id'])],
            source_ref=f'walking_summary:contacts:{index}',
            evidence=dict(publication_version=event.get('publication_version'),
                          position_source='landing_positions_m_at_publication',
                          metric_source='independent_contact_and_relationship_evidence',
                          issue_refs=[i for i, issue in enumerate(summary['issues'])
                                      if issue.get('frame_index') == event['touch_sample']]),
            quality_exclusion=contact.get('exclusion')))
    return records
