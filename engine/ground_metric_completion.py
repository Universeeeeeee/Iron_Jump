"""Complete report statistics from observed landings without changing detection.

Raw contact certificates remain intact; completed footfalls retain source_records. Derived values record their
inputs and assumptions separately, including any inferred release boundary.
"""
from copy import deepcopy
from math import isfinite
from statistics import mean, median


POLICY = 'observed_landing_sequence_completion_v2'


def _number(value):
    return isinstance(value, (int, float)) and isfinite(value)


def complete_ground_metrics(summary, mode):
    if not summary or summary.get('metric_completion', {}).get('policy') == POLICY:
        return summary
    if summary.get('metric_completion'):
        summary = deepcopy(summary)
        for kind, saved in summary['metric_completion'].get('source_records', {}).items():
            for record in summary.get(kind, []):
                cid = str(record.get('contact_id', record.get('id')))
                for key, value in saved.get(cid, {}).items():
                    if value is None:
                        record.pop(key, None)
                    else:
                        record[key] = value
        for key, value in summary['metric_completion'].get('original_aggregates', {}).items():
            if key.startswith('groups.all.'):
                summary['groups']['all'][key.removeprefix('groups.all.')] = value
            else:
                summary[key] = value
        summary.pop('recognized_measurements', None)
    from reporting.recognized_gait import recognized_gait
    data = recognized_gait(summary)
    if not data['rows']:
        return summary
    result = deepcopy(summary)
    rows = data['rows']
    contacts = {(c.get('epoch', 0), c['id']): c for c in summary.get('contacts', [])}
    methods = []
    for row in rows:
        contact = contacts.get((row['epoch'], row['contact_id']), {})
        if row['position_m'] is None:
            position = row.get('raw_position_m')
            if not _number(position):
                position = contact.get('position_m')
            if _number(position):
                row['position_m'] = position
                row['position_basis'] = 'observed_contact_center'
                methods.append({'contact_id': row['contact_id'], 'metric': 'position_m',
                                'basis': 'observed_contact_center'})
        if row['contact_s'] is None and not row['contact_exclusion'] == 'stop_interval':
            span = row['observed_span_s']
            if _number(span) and span > 0:
                row['contact_s'] = span
                row['contact_basis'] = '光学遮挡时长'
                methods.append({'contact_id': row['contact_id'], 'metric': 'contact_s',
                                'basis': 'observed_occlusion_span'})

    def linked(a, b):
        if b['timestamp_s'] <= a['timestamp_s']:
            return False
        left, right = a['relative_time_s'], b['relative_time_s']
        if left is not None and right is not None:
            if any(left < stop['end_s'] and right > stop['start_s'] for stop in summary.get('stops', [])):
                return False
            if any(issue.get('time_s') is not None and left < issue['time_s'] <= right
                   and issue.get('code') in {'counter_reset', 'out_of_order_or_reset', 'turn_detected',
                                             'device_changed', 'layout_mismatch', 'frame_gap',
                                             'data_timeout', 'disconnected'}
                   for issue in summary.get('issues', [])):
                return False
        # A local attribution ambiguity can change the identity epoch without
        # resetting the device clock. It does not erase the two known onsets.
        return True

    known_intervals = [r['step_time_s'] for r in rows if r['step_time_s'] is not None and r['step_time_s'] > 0]
    observed_intervals = [b['timestamp_s'] - a['timestamp_s'] for a, b in zip(rows, rows[1:]) if linked(a, b)]
    cadence_interval = median(known_intervals) if known_intervals else (
        median(sorted(observed_intervals)[:max(1, len(observed_intervals) // 2)]) if observed_intervals else None)
    for a, b in zip(rows, rows[1:]):
        b['interval_steps'] = (max(1, round((b['timestamp_s'] - a['timestamp_s']) / cadence_interval))
                               if b['step_time_s'] is None and cadence_interval and linked(a, b) else 1)
    periods = {}
    for i in range(len(rows) - 2):
        a, b, c = rows[i:i + 3]
        if linked(a, b) and linked(b, c):
            periods[i] = 2 * (c['timestamp_s'] - a['timestamp_s']) / (b['interval_steps'] + c['interval_steps'])
    duties = [rows[i]['contact_s'] / period for i, period in periods.items()
              if rows[i]['contact_s'] is not None and 0 < rows[i]['contact_s'] <= period
              and rows[i]['contact_exclusion'] != 'stop_interval']
    # Learn a contact/cycle ratio from this capture; never substitute a fixed
    # population value or manufacture support when no release was observed.
    for i, row in enumerate(rows):
        if row['contact_s'] is None and duties and periods and row['contact_exclusion'] != 'stop_interval':
            period = periods.get(i, median(periods.values()))
            row['contact_s'] = period * median(duties)
            row['contact_basis'] = '本次接触时序'
            methods.append({'contact_id': row['contact_id'], 'metric': 'contact_s',
                            'basis': 'within_capture_duty_ratio', 'cycle_s': period,
                            'duty_ratio': median(duties)})
        row['contact_included'] = row['contact_s'] is not None and row['contact_exclusion'] != 'stop_interval'
        if i == 0:
            continue
        prev = rows[i - 1]
        if not linked(prev, row):
            continue
        row['interval_time_s'] = row['timestamp_s'] - prev['timestamp_s']
        row['step_time_s'] = row['interval_time_s'] / row['interval_steps']
        if prev['position_m'] is not None and row['position_m'] is not None:
            row['interval_distance_m'] = abs(row['position_m'] - prev['position_m'])
            row['step_length_m'] = row['interval_distance_m'] / row['interval_steps']
            row['speed_m_s'] = row['step_length_m'] / row['step_time_s']
        row['relation_note'] = '相邻已识别落脚'
        if row['interval_steps'] > 1:
            row['relation_note'] = '按本次步频分配落脚区间'
            methods.append({'contact_id': row['contact_id'], 'metric': 'step_time_s',
                            'basis': 'within_capture_cadence', 'interval_steps': row['interval_steps'],
                            'cadence_interval_s': cadence_interval})

    cycles = []
    for i, period in periods.items():
        a, b, c = rows[i:i + 3]
        cycle = {'from_id': a['contact_id'], 'to_id': c['contact_id'], 'duration_s': period}
        if a['position_m'] is not None and c['position_m'] is not None:
            cycle['length_m'] = 2 * abs(c['position_m'] - a['position_m']) / (b['interval_steps'] + c['interval_steps'])
        if a['contact_included'] and a['contact_s'] <= period:
            cycle['contact_s'] = a['contact_s']
            cycle['swing_s'] = period - a['contact_s']
        relevant = rows[max(0, i - 1):i + 2]
        if all(r['contact_included'] for r in relevant):
            left, right = a['timestamp_s'], c['timestamp_s']
            spans = [(r['timestamp_s'], r['timestamp_s'] + r['contact_s']) for r in relevant]
            if b['interval_steps'] + c['interval_steps'] > 2:
                left, right = 0., period
                spans = [(0., a['contact_s']), (period / 2, period / 2 + b['contact_s'])]
                if i:
                    spans.append((-period / 2, -period / 2 + rows[i - 1]['contact_s']))
            bounds = sorted({left, right, *[max(left, min(right, t)) for span in spans for t in span]})
            support = [0., 0., 0.]
            for start, end in zip(bounds, bounds[1:]):
                count = sum(x <= (start + end) / 2 < y for x, y in spans)
                if count > 2:
                    break
                support[count] += end - start
            else:
                cycle.update(zip(('flight_s', 'single_support_s', 'double_support_s'), support))
        cycles.append(cycle)

    intervals = [r for r in rows if r['step_time_s'] is not None]
    spatial = [r for r in intervals if r['step_length_m'] is not None]
    complete = [r for r in rows if r['contact_included']]
    average = lambda values: mean(values) if values else None
    data.update(policy=POLICY, interval_count=len(intervals), spatial_interval_count=len(spatial),
                contact_count=len(complete), estimated_contact_count=sum(m['metric'] == 'contact_s' for m in methods),
                mean_contact_s=average([r['contact_s'] for r in complete]),
                mean_step_m=average([r['step_length_m'] for r in spatial]),
                speed_m_s=sum(r['step_length_m'] for r in spatial)/sum(r['step_time_s'] for r in spatial) if spatial else None,
                cadence_per_min=60*len(intervals)/sum(r['step_time_s'] for r in intervals) if intervals else None,
                sample_sets={'contacts': [r['contact_id'] for r in complete],
                             'intervals': [[r['from_contact_id'], r['contact_id']] for r in intervals],
                             'spatial_intervals': [[r['from_contact_id'], r['contact_id']] for r in spatial]})
    original = {}
    def fill(key, value):
        if result.get(key) is None and value is not None:
            original[key] = result.get(key)
            result[key] = value
    # Overall elapsed time needs an observed first/last landing, not a complete
    # gait cycle. An unresolved terminal release contributes no extra tail.
    last = rows[-1]
    duration = last['timestamp_s'] - rows[0]['timestamp_s']
    duration += last['contact_s'] if last['contact_included'] else 0
    if duration > 0 and not any(issue.get('code') in {'counter_reset', 'out_of_order_or_reset', 'device_changed'}
                                for issue in summary.get('issues', [])):
        fill('duration_s', duration)
    if mode == 'walk':
        for key, source in [('mean_step_m', 'mean_step_m'), ('mean_contact_s', 'mean_contact_s'),
                            ('cadence_per_min', 'cadence_per_min'), ('walking_speed_m_s', 'speed_m_s')]:
            fill(key, data[source])
        for key, source in [('mean_stride_m', 'length_m'), ('single_support_s', 'single_support_s'),
                            ('double_support_s', 'double_support_s')]:
            fill(key, average([c[source] for c in cycles if source in c]))
        if rows[0]['position_m'] is not None and last['position_m'] is not None and result.get('duration_s'):
            fill('passage_speed_m_s', abs(last['position_m'] - rows[0]['position_m']) / result['duration_s'])
    else:
        fill('running_speed_m_s', data['speed_m_s'])
        group = result.get('groups', {}).get('all', {})
        for key in ('duration_s', 'length_m', 'contact_s', 'swing_s', 'flight_s', 'single_support_s', 'double_support_s'):
            values = [c[key] for c in cycles if key in c]
            if key in group and group[key]['mean'] is None and values:
                original['groups.all.' + key] = deepcopy(group[key])
                group[key] = {'mean': mean(values), 'count': len(values)}
    result['recognized_measurements'] = data
    result['metric_completion'] = {'policy': POLICY, 'methods': methods, 'original_aggregates': original,
                                   'cycles': cycles, 'assumptions': ['alternating_recognized_landings',
                                   'observed_occlusion_as_contact', 'within_capture_duty_ratio_for_missing_release',
                                   'within_capture_cadence_for_unobserved_step_spacing']}
    _complete_detail_records(result, data, mode)
    return result


def _complete_detail_records(summary, measurements, mode):
    """Use the same computed values in overview, accepted-footfall details and export.

Unpublished candidates remain diagnostic records. Preserve the exact original
certificates for every completed field instead of replacing the raw evidence.
    """
    rows = {(r['epoch'], r['contact_id']): r for r in measurements['rows']}
    source = {}

    def fill(record, key, value, basis):
        if not _number(value) or record.get(key, {}).get('valid'):
            return
        cid = str(record['contact_id'])
        source.setdefault(cid, {})[key] = deepcopy(record.get(key))
        record[key] = {'value': value, 'valid': True, 'missing_reason': None,
                       'evidence': {'basis': basis, 'policy': POLICY}}

    for record in summary.get('footfalls', []):
        row = rows.get((record.get('epoch', 0), record['contact_id']))
        if row is None:
            continue
        if row['contact_included']:
            fill(record, 'contact_s', row['contact_s'], 'completed_contact_timing')
            if row['relative_time_s'] is not None:
                fill(record, 'lift_s', row['relative_time_s'] + row['contact_s'], 'completed_release_timing')
        if mode == 'walk':
            fill(record, 'centre_m', row['position_m'], row['position_basis'])
        for key, value in [('step_time_s', row['step_time_s']),
                           ('step_length_m', row['step_length_m']), ('speed_m_s', row['speed_m_s'])]:
            fill(record, key, value, 'completed_landing_interval')
    summary['metric_completion']['source_records'] = {'footfalls': source}
