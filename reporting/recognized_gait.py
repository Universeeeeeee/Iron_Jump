"""One measurement policy for accepted footprints and all report consumers.

Recognition is retained independently of metric eligibility. Unresolved spans
are observations, not single-foot contact estimates or single-step distances.
"""
from html import escape
from config.footfall_events import active_touch_events

POLICY = 'recognized_independent_metrics_v2'
NONSTEPS = {'excluded_nonstep', 'associated_fragment'}


def _touch(contact):
    value = contact.get('touch_s')
    if isinstance(value, dict):
        return value.get('value') if value.get('valid') else None
    if contact.get('confirmed') and contact.get('touch_known', True):
        return contact.get('start')
    return None


def _events(summary):
    if 'event_publications' in summary:
        return active_touch_events(summary['event_publications']), 'published_events'
    # Older running snapshots already certify individual touch metrics. Adapt
    # those certificates, without changing the detector or the saved snapshot.
    events = []
    origins = {}
    for c in summary.get('contacts', []):
        if c.get('touch_sample') is not None and _touch(c) is not None:
            origins.setdefault(c.get('epoch', 0), c['touch_sample'] / 1000 - _touch(c))
    for c in summary.get('contacts', []):
        touch = _touch(c)
        if touch is None or c.get('candidate_outcome') in NONSTEPS:
            continue
        sample = c.get('touch_sample')
        events.append(dict(contact_id=c['id'], epoch=c.get('epoch', 0),
                           event_id=f"legacy:{c.get('epoch', 0)}:{c['id']}",
                           touch_sample=sample if sample is not None else (touch + origins.get(c.get('epoch', 0), 0)) * 1000))
    return events, 'legacy_valid_touches'


def _position(contact):
    if 'landing_reference' in contact:
        ref = contact['landing_reference']
        return (ref.get('value') if ref.get('valid') else None,
                ref.get('basis'), ref.get('sample'))
    # Historical publication-time positions cannot be turned into onset points.
    # Retain only an independently validated stance reference, with its own name.
    for key, basis in (('centre_m', 'legacy_stance_center'), ('toe_m', 'legacy_stable_toe')):
        metric = contact.get(key)
        if isinstance(metric, dict) and metric.get('valid'):
            return metric['value'], basis, None
    if ('centre_m' not in contact and contact.get('confirmed')
            and contact.get('position_known', True) and not contact.get('exclusion')):
        return contact.get('position_m'), 'legacy_stance_center', None
    return None, 'unavailable', None


def recognized_gait(summary):
    if 'recognized_measurements' in summary:
        from copy import deepcopy
        return deepcopy(summary['recognized_measurements'])
    contacts = {(c.get('epoch', 0), c['id']): c for c in summary.get('contacts', [])}
    events, source = _events(summary)
    events = sorted(events, key=lambda e: (e['epoch'], e['touch_sample'], e['contact_id']))
    active = {(e['epoch'], e['contact_id']) for e in events}
    certified_steps = set()
    for step in summary.get('steps', []):
        timing = step.get('time_s')
        valid = timing.get('valid', False) if isinstance(timing, dict) else timing is not None and timing > 0
        if valid:
            certified_steps.add((step['from_id'], step['to_id']))
    origins = {}
    for e in events:
        touch = _touch(contacts.get((e['epoch'], e['contact_id']), {}))
        if touch is not None:
            origins.setdefault(e['epoch'], e['touch_sample'] / 1000 - touch)
    barriers = []
    for key, c in contacts.items():
        if key in active or c.get('candidate_outcome') in NONSTEPS:
            continue
        n = c.get('first_seen_sample', c.get('touch_sample'))
        if n is None and c.get('start') is not None:
            n = (c['start'] + origins.get(key[0], 0)) * 1000
        if n is not None:
            barriers.append((key[0], n / 1000))
    for c in summary.get('candidate_decisions', []):
        if c.get('outcome') not in {'pending', 'unresolved'} or c.get('source') != 'narrow':
            continue
        if c.get('first_sample') is not None:
            barriers.append((c.get('epoch', 0), c['first_sample'] / 1000))
    rows = []
    for event in events:
        c = contacts.get((event['epoch'], event['contact_id']), {})
        start = c.get('observed_start_s', c.get('start', _touch(c)))
        end = c.get('observed_end_s', c.get('end'))
        lift = c.get('lift_s', {})
        if end is None and lift.get('valid'):
            end = lift['value']
        span = end - start if start is not None and end is not None and end >= start else None
        measured = c.get('contact_s', {})
        duration = measured.get('value') if measured.get('valid') else None
        if 'contact_s' not in c and c.get('confirmed') and not c.get('exclusion'):
            duration = span
        stopped = measured.get('missing_reason') == 'stop_interval' or (
            start is not None and end is not None and any(
                start < stop['end_s'] and end > stop['start_s'] for stop in summary.get('stops', [])))
        included = duration is not None and not stopped
        exclusion = 'stop_interval' if stopped else None if included else measured.get('missing_reason') or 'incomplete_contact'
        basis = '停步，不纳入均值' if stopped else '完整边界' if included else '遮挡跨度，非单脚接触' if span is not None else '未完整观测离地'
        position, position_basis, position_sample = _position(c)
        row = dict(contact_id=event['contact_id'], epoch=event['epoch'], event_id=event['event_id'],
                   timestamp_s=event['touch_sample'] / 1000, relative_time_s=_touch(c),
                   position_m=position, position_basis=position_basis, position_sample=position_sample,
                   raw_position_m=summary.get('landing_positions_m', {}).get(str(event['contact_id'])),
                   contact_s=duration, observed_span_s=span, contact_basis=basis,
                   contact_included=included, contact_exclusion=exclusion,
                   from_contact_id=None, interval_time_s=None, interval_distance_m=None,
                   step_time_s=None, step_length_m=None, speed_m_s=None, relation_note='首次落脚')
        if rows:
            prev = rows[-1]
            dt = row['timestamp_s'] - prev['timestamp_s']
            row['from_contact_id'] = prev['contact_id']
            same_epoch = prev['epoch'] == row['epoch']
            same_reference = prev['position_basis'] == position_basis
            if same_epoch and dt > 0:
                row['interval_time_s'] = dt
                if same_reference and prev['position_m'] is not None and position is not None:
                    row['interval_distance_m'] = abs(position - prev['position_m'])
            reason = '采集连续性中断' if not same_epoch else '同时落脚' if dt <= 0 else ''
            if (not reason and (prev['contact_id'], row['contact_id']) not in certified_steps
                    and any(epoch == row['epoch'] and prev['timestamp_s'] < t <= row['timestamp_s'] for epoch, t in barriers)):
                reason = '区间存在未确认脚印，可能跨步'
            a, b = prev['relative_time_s'], row['relative_time_s']
            if not reason and a is not None and b is not None:
                if any(a < stop['end_s'] and b > stop['start_s'] for stop in summary.get('stops', [])):
                    reason = '跨越停步区间'
                if any(issue.get('time_s') is not None and a < issue['time_s'] <= b
                       and issue.get('code') in {'frame_gap', 'data_timeout', 'out_of_order_or_reset', 'counter_reset', 'turn_detected'}
                       for issue in summary.get('issues', [])):
                    reason = '采集连续性中断'
            row['relation_note'] = reason or '相邻已确认落脚'
            if not reason:
                row['step_time_s'] = dt
                row['step_length_m'] = row['interval_distance_m']
                if row['step_length_m'] is not None:
                    row['speed_m_s'] = row['step_length_m'] / dt
                elif not same_reference:
                    row['relation_note'] += '；位置参考口径不同'
                else:
                    row['relation_note'] += '；缺少可比的位置参考'
        rows.append(row)
    intervals = [r for r in rows if r['step_time_s'] is not None]
    spatial = [r for r in intervals if r['step_length_m'] is not None]
    complete = [r for r in rows if r['contact_included']]
    return dict(policy=POLICY, source=source, supported='event_publications' in summary or any(
                    'touch_s' in c or 'confirmed' in c for c in summary.get('contacts', [])),
                rows=rows, recognized_steps=len(rows), interval_count=len(intervals),
                mean_contact_s=sum(r['contact_s'] for r in complete)/len(complete) if complete else None,
                contact_count=len(complete), observed_span_count=sum(r['observed_span_s'] is not None and not r['contact_included'] for r in rows),
                estimated_contact_count=0, spatial_interval_count=len(spatial),
                mean_step_m=sum(r['step_length_m'] for r in spatial)/len(spatial) if spatial else None,
                speed_m_s=sum(r['step_length_m'] for r in spatial)/sum(r['step_time_s'] for r in spatial) if spatial else None,
                cadence_per_min=60*len(intervals)/sum(r['step_time_s'] for r in intervals) if intervals else None,
                sample_sets={'contacts': [r['contact_id'] for r in complete],
                             'intervals': [[r['from_contact_id'], r['contact_id']] for r in intervals],
                             'spatial_intervals': [[r['from_contact_id'], r['contact_id']] for r in spatial]})


def recognized_html(summary):
    data = recognized_gait(summary)
    if not data['rows']:
        return ''
    text = '<h3>已识别脚印测量</h3><p>保留每个已确认落脚。新记录采用首次有效光学接触的中心参考；旧记录保留有效的位置参考。'
    if data.get('estimated_contact_count', 0):
        text += f"接触列包含 {data['estimated_contact_count']} 条按光学遮挡或本次时序补全的结果，依据见说明。可靠观测见左右参数表。</p>"
    else:
        text += '未决区间保留距离，单脚边界未知的遮挡跨度单列。</p>'
    columns = [('position_m','参考位置(m)'),('step_time_s','步间(s)'),('step_length_m','单步距离(m)'),
               ('interval_distance_m','区间距离(m)'),('contact_s','接触(s)'),('observed_span_s','遮挡跨度(s)')]
    text += '<table cellspacing="8"><tr><th>序号</th>' + ''.join('<th>'+label+'</th>' for _,label in columns) + '<th>说明</th></tr>'
    for i, row in enumerate(data['rows']):
        values = [str(i+1)] + [f'{row[key]:.3f}' if row[key] is not None else '—' for key,_ in columns]
        values.append(row['relation_note'] + '；' + row['contact_basis'])
        text += '<tr>' + ''.join('<td>'+escape(v)+'</td>' for v in values) + '</tr>'
    return text + '</table>'
