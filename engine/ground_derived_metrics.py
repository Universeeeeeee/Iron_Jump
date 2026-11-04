"""Versioned formulas over existing contacts and relationships, in SI units."""
from math import atan, degrees, isfinite

from engine.ground_metric_evidence import metric
from engine.ground_contact_phases import PHASE_CODES


G = 9.80665
SIGNED_METRICS = {'acceleration_m_s2', 'toe_acceleration_m_s2',
                  'imbalance_theory_percent', 'imbalance_sample_percent'}
STEP_CODES = ('toe_step_length_m', 'toe_speed_m_s', 'acceleration_m_s2', 'toe_acceleration_m_s2')
RUN_STEP_CODES = ('flight_height_m', 'stride_angle_deg')
RUN_CONTACT_CODES = ('duty_factor_percent', 'imbalance_theory_percent', 'imbalance_sample_percent')
FORMULAS = {
    'flight_height_m': 'g*single_flight_s**2/8; g=9.80665; equal_takeoff_landing_height',
    'stride_angle_deg': 'degrees(atan(4*flight_height_m/step_length_m)); run_step_toe_reference',
    'acceleration_m_s2': '(current_step_speed-previous_step_speed)/(current_step_time+previous_step_time)',
    'duty_factor_percent': '100*contact_s/(contact_s+following_flight_s); contact_side; not_stride_duty_factor',
    'imbalance_theory_percent': '100*(middle_contact-mean(neighbours))/mean(neighbours); signed_manual_theory_v1',
    'imbalance_sample_percent': '100*(middle_contact-mean(neighbours))/middle_contact; signed_sample_candidate_v1',
    'toe_speed_m_s': 'toe_step_length_m/step_time_s',
    'toe_acceleration_m_s2': '(current_toe_speed-previous_toe_speed)/(current_step_time+previous_step_time)',
    'toe_spatial_reference': 'stable_fully_expanded_optical_platform_leading_edge_v1',
}


def _value(item):
    if isinstance(item, dict):
        item = item.get('value') if item.get('valid') else None
    return item if isinstance(item, (float, int)) and not isinstance(item, bool) and isfinite(item) else None


def derive_metrics(summary, mode):
    contacts = {r['id']: r for r in summary['contacts']}
    phases = {r['contact_id']: r for r in summary.get('contact_phases', {}).get('contacts', [])}
    result = {kind: [] for kind in ('contacts', 'steps', 'cycles')}
    links = {(s['from_id'], s['to_id']): s for s in summary['steps']
             if _value(s['time_s']) is not None and _value(s['time_s']) > 0}
    toes = {cid: _value(p['toe_m']) for cid, p in phases.items()}
    # Existing certified running toe evidence is independently usable.
    if mode == 'run':
        toes = {cid: _value(row.get('toe_m')) for cid, row in contacts.items()}

    def distance(a, b):
        x, y = toes.get(a), toes.get(b)
        return metric(abs(y - x) if x is not None and y is not None else None,
                      None if x is not None and y is not None else 'toe_reference_unavailable')

    contact_metrics = {}
    for row in summary['contacts']:
        metrics = {code: phases.get(row['id'], {}).get('metrics', {}).get(code,
                   metric(reason='contact_phase_not_observed')) for code in PHASE_CODES}
        if mode == 'run':
            metrics.update({code: metric(reason='adjacent_contacts_unavailable') for code in
                            ('imbalance_theory_percent', 'imbalance_sample_percent')})
            metrics['duty_factor_percent'] = metric(reason='following_flight_unavailable')
        contact_metrics[row['id']] = metrics
        result['contacts'].append({'metrics': metrics, 'source_contact_ids': [row['id']]})

    previous = None
    previous_metrics = None
    for step in summary['steps']:
        a, b = step['from_id'], step['to_id']
        dt = _value(step['time_s'])
        metrics = {'toe_step_length_m': distance(a, b) if (a, b) in links else metric(reason='step_relationship_unavailable')}
        length = _value(metrics['toe_step_length_m'])
        metrics['toe_speed_m_s'] = metric(length / dt if length is not None and dt and dt > 0 else None,
                                          None if length is not None and dt and dt > 0 else 'length_or_time_unavailable')
        refs = [a, b]
        for target, speed_key, current, prior in (
            ('acceleration_m_s2', 'speed_m_s', step, previous),
            ('toe_acceleration_m_s2', 'toe_speed_m_s', metrics, previous_metrics)):
            v = _value(current.get(speed_key))
            pv = _value(prior.get(speed_key)) if prior else None
            pdt = _value(previous['time_s']) if previous else None
            continuous = (previous is not None and previous['to_id'] == a
                          and contacts[previous['from_id']]['epoch'] == contacts[a]['epoch'] == contacts[b]['epoch'])
            valid = continuous and v is not None and pv is not None and dt and pdt and dt > 0 and pdt > 0
            metrics[target] = metric((v - pv) / (dt + pdt) if valid else None,
                                     None if valid else 'adjacent_speeds_unavailable')
            if valid:
                refs = [previous['from_id'], a, b]
        if mode == 'run':
            flight = _value(step.get('flight_s'))
            valid_flight = flight is not None and flight >= 0
            height = G * flight ** 2 / 8 if valid_flight else None
            metrics['flight_height_m'] = metric(height, None if valid_flight else 'flight_not_observed')
            step_length = _value(step['length_m'])
            angle_valid = height is not None and step_length is not None and step_length > 0
            metrics['stride_angle_deg'] = metric(degrees(atan(4 * height / step_length)) if angle_valid else None,
                                                 None if angle_valid else 'flight_or_distance_unavailable')
            contact = _value(contacts[a]['contact_s'])
            duty_valid = (contact is not None and contact > 0 and valid_flight and dt is not None
                          and contacts[a].get('touch_sample') is not None and contacts[a].get('lift_sample') is not None
                          and contacts[a]['epoch'] == contacts[b]['epoch'])
            contact_metrics[a]['duty_factor_percent'] = metric(100 * contact / (contact + flight) if duty_valid else None,
                                                               None if duty_valid else 'contact_or_flight_unavailable')
            index = next(i for i, row in enumerate(summary['contacts']) if row['id'] == a)
            result['contacts'][index]['source_contact_ids'] = [a, b]
        result['steps'].append({'metrics': metrics, 'source_contact_ids': refs})
        previous, previous_metrics = step, metrics

    if mode == 'run':
        # Only the producer's actual consecutive relationships form a triple.
        outgoing = {a: b for a, b in links}
        for a, b in links:
            c = outgoing.get(b)
            if c is None or len({contacts[i]['epoch'] for i in (a, b, c)}) != 1:
                continue
            values = [_value(contacts[i]['contact_s']) for i in (a, b, c)]
            if any(v is None or v <= 0 for v in values):
                continue
            if any(contacts[i].get('touch_sample') is None or contacts[i].get('lift_sample') is None for i in (a, b, c)):
                continue
            if not contacts[a].get('label') or contacts[a]['label'] != contacts[c].get('label') or contacts[a]['label'] == contacts[b].get('label'):
                continue
            ideal = (values[0] + values[2]) / 2
            delta = values[1] - ideal
            contact_metrics[b]['imbalance_theory_percent'] = metric(100 * delta / ideal)
            contact_metrics[b]['imbalance_sample_percent'] = metric(100 * delta / values[1])
            index = next(i for i, row in enumerate(summary['contacts']) if row['id'] == b)
            result['contacts'][index]['source_contact_ids'] = [a, b, c]
    for cycle in summary['cycles']:
        length = distance(cycle['from_id'], cycle['to_id']) if _value(cycle['duration_s']) is not None else metric(reason='incomplete_cycle')
        result['cycles'].append({'metrics': {'toe_stride_length_m': length},
                                 'source_contact_ids': [cycle['from_id'], cycle['to_id']]})
    return result
