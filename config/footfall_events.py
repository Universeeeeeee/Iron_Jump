"""Pure snapshot validation and event revision selection."""

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

