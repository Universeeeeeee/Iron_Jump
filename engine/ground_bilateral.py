"""Observed ground metrics, frozen before report completion/estimation."""
from collections import Counter
from math import isfinite
from statistics import mean, pstdev
from engine.ground_derived_metrics import (derive_metrics, FORMULAS, SIGNED_METRICS,
    STEP_CODES, RUN_STEP_CODES, RUN_CONTACT_CODES)
from engine.ground_contact_phases import PHASE_CODES


VERSION = 'ground_bilateral_v2'
PHASES = ('stance_phase', 'swing_phase', 'single_support',
          'total_double_support', 'load_response', 'pre_swing')
CONTACT_METRICS = {'contact_time_s': 'contact_s'}
STEP_METRICS = {'step_length_m': 'length_m', 'step_time_s': 'time_s', 'speed_m_s': 'speed_m_s'}
CYCLE_METRICS = ('gait_cycle_s', 'stride_length_m') + tuple(
    f'{phase}_{unit}' for phase in PHASES for unit in ('s', 'percent'))


def value(item):
    if isinstance(item, dict):
        item = item.get('value') if item.get('valid') else None
    return item if isinstance(item, (int, float)) and not isinstance(item, bool) and isfinite(item) else None


def metric(number=None, reason=None):
    number = value(number)
    return {'value': number if reason is None else None,
            'valid': number is not None and reason is None,
            'missing_reason': reason or ('not_observed' if number is None else None)}


def observed(row, key):
    source = row.get(key)
    reason = source.get('missing_reason') if isinstance(source, dict) else None
    return metric(value(source), reason)


def _cycle_metrics(cycle, contacts, sequence):
    a, z = (contacts.get(cycle.get(key)) for key in ('from_id', 'to_id'))
    result = {key: metric(reason='incomplete_cycle') for key in CYCLE_METRICS}
    if a is None or z is None:
        return result
    start, end = value(a.get('touch_s')), value(z.get('touch_s'))
    duration = value(cycle.get('duration_s'))
    if (duration is None or duration <= 0 or start is None or end is None
            or a['epoch'] != z['epoch'] or not a.get('label') or a['label'] != z.get('label')):
        return result
    result['gait_cycle_s'] = metric(duration)
    result['stride_length_m'] = observed(cycle, 'length_m')
    contact = value(a.get('contact_s'))
    lift = value(a.get('lift_s'))
    stance_reason = (a.get('contact_s', {}).get('missing_reason') or
                     ('touch_not_observed' if a.get('touch_sample') is None else None) or
                     ('lift_not_observed' if a.get('lift_sample') is None else None))
    if contact is None or lift is None or not start < lift <= end:
        stance_reason = stance_reason or 'incomplete_contact'
    result['stance_phase_s'] = metric(contact, stance_reason)
    result['swing_phase_s'] = metric(end - lift if lift is not None else None, stance_reason)

    # Entry may hide support by the opposite foot outside the measuring area.
    # A preceding, observed opposite contact is needed to close that boundary.
    index = next(i for i, row in enumerate(sequence) if row['id'] == a['id'])
    previous = sequence[index - 1] if index else None
    support_reason = None
    if (previous is None or previous['epoch'] != a['epoch']
            or not previous.get('label') or previous['label'] == a['label']):
        support_reason = 'entry_support_not_observed'
    elif value(previous.get('contact_s')) is None or previous.get('lift_sample') is None:
        support_reason = 'opposite_contact_not_observed'
    if value(cycle.get('single_support_s')) is None or value(cycle.get('double_support_s')) is None:
        support_reason = support_reason or 'support_continuity_unknown'
    relevant = [row for row in sequence if row['id'] != z['id']
                and value(row.get('touch_s')) is not None and value(row['touch_s']) < end
                and (value(row.get('lift_s')) is None or value(row['lift_s']) > start)]
    if any(row['epoch'] != a['epoch'] or not row.get('label')
           or value(row.get('contact_s')) is None or row.get('lift_sample') is None for row in relevant):
        support_reason = support_reason or 'opposite_contact_not_observed'
    support_reason = support_reason or stance_reason
    spans = [(value(row['touch_s']), value(row['lift_s']), row['label']) for row in relevant]
    single = double = loading = pre = 0.
    if not support_reason:
        bounds = sorted({start, end, *[max(start, min(end, t)) for lo, hi, _ in spans for t in (lo, hi)]})
        ds = []
        for lo, hi in zip(bounds, bounds[1:]):
            active = [label for x, y, label in spans if x <= (lo + hi) / 2 < y]
            if len(active) > 2 or len(active) != len(set(active)):
                support_reason = 'ambiguous_contacts'
                break
            if active == [a['label']]:
                single += hi - lo
            if len(active) == 2:
                double += hi - lo
                if ds and abs(ds[-1][1] - lo) < 1e-9:
                    ds[-1] = (ds[-1][0], hi)
                else:
                    ds.append((lo, hi))
        if not support_reason:
            loading = sum(hi - lo for lo, hi in ds if abs(lo - start) < 1e-9)
            pre = sum(hi - lo for lo, hi in ds if abs(hi - lift) < 1e-9)
            # DS1/DS2 describe separate transitions, not an arbitrary partition.
            if abs(loading + pre - double) > 1e-9:
                support_reason = 'nonstandard_support_sequence'
    for name, number in [('single_support', single), ('total_double_support', double),
                         ('load_response', loading), ('pre_swing', pre)]:
        result[name + '_s'] = metric(number, support_reason)
    for name in PHASES:
        source = result[name + '_s']
        result[name + '_percent'] = metric(
            100 * source['value'] / duration if source['valid'] else None, source['missing_reason'])
    return result


def _statistics(records, code):
    def summarize(side):
        selected = [r for r in records if side == 'all' or r['side'] == side]
        valid = [r for r in selected if r['metrics'][code]['valid']]
        numbers = [r['metrics'][code]['value'] for r in valid]
        average = mean(numbers) if numbers else None
        sd = pstdev(numbers) if len(numbers) >= 2 else None
        return {'count': len(numbers), 'mean': average, 'min': min(numbers) if numbers else None,
                'max': max(numbers) if numbers else None, 'std': sd,
                'cv_percent': 100 * sd / average if code not in SIGNED_METRICS and sd is not None and average > 1e-12 else None,
                'source_refs': [r['source_ref'] for r in valid],
                'missing_reasons': dict(Counter(r['metrics'][code]['missing_reason'] for r in selected
                                                if not r['metrics'][code]['valid']))}
    stats = {side: summarize(side) for side in ('all', 'left', 'right', 'unknown')}
    left, right = stats['left'], stats['right']
    enough = min(left['count'], right['count']) >= 3
    difference = left['mean'] - right['mean'] if left['count'] and right['count'] else None
    denominator = (left['mean'] + right['mean']) / 2 if difference is not None else None
    stats['difference'] = metric(difference)
    stats['si_percent'] = metric(100 * abs(difference) / denominator if enough and denominator > 1e-12 else None,
        'insufficient_bilateral_samples' if not enough else 'zero_reference' if denominator <= 1e-12 else None)
    stats['diff_percent'] = metric(100 * difference / left['mean'] if enough and left['mean'] > 1e-12 else None,
        'insufficient_bilateral_samples' if not enough else 'zero_reference' if left['mean'] <= 1e-12 else None)
    if code in SIGNED_METRICS:
        stats['si_percent'] = metric(reason='relative_comparison_not_applicable')
        stats['diff_percent'] = metric(reason='relative_comparison_not_applicable')
    return stats


def build_bilateral(summary, mode, starting_foot):
    """Only called on new processor summaries; never upgrades saved reports."""
    contacts = {row['id']: row for row in summary['contacts']}
    sequence = sorted((row for row in contacts.values()
                       if row.get('candidate_outcome') not in {'excluded_nonstep', 'associated_fragment'}),
                      key=lambda row: (value(row.get('touch_s')) if value(row.get('touch_s')) is not None else float('inf'), row['id']))
    records = {kind: [] for kind in ('contacts', 'steps', 'cycles')}
    derived = derive_metrics(summary, mode)
    ending_cycles = {row['to_id']: row for row in summary['cycles']}
    step_metrics = {**STEP_METRICS, **({'flight_time_s': 'flight_s'} if mode == 'run' else {})}
    for kind, rows in ((kind, summary[kind]) for kind in records):
        for i, row in enumerate(rows):
            target = contacts.get(row.get('to_id'), {})
            side = row.get('side', target.get('side', 'unknown'))
            if starting_foot not in {'Left', 'Right'}:
                side = 'unknown'
            if kind == 'cycles':
                metrics = _cycle_metrics(row, contacts, sequence)
            else:
                mapping = CONTACT_METRICS if kind == 'contacts' else step_metrics
                metrics = {code: observed(row, key) for code, key in mapping.items()}
                if kind == 'contacts' and (row.get('touch_sample') is None or row.get('lift_sample') is None):
                    metrics['contact_time_s'] = metric(reason=metrics['contact_time_s']['missing_reason'] or 'contact_boundary_not_observed')
                if kind == 'steps':
                    dt = value(row.get('time_s'))
                    metrics['cadence_steps_per_min'] = metric(60 / dt if dt and dt > 0 else None)
                    cycle = ending_cycles.get(row['to_id'], {})
                    period = value(cycle.get('duration_s'))
                    metrics['step_time_percent'] = metric(100 * dt / period if dt is not None and period and 0 < dt < period else None,
                                                         None if dt is not None and period and 0 < dt < period else 'incomplete_cycle')
            ids = [row['id']] if kind == 'contacts' else [row.get('from_id'), row.get('to_id')]
            metrics.update(derived[kind][i]['metrics'])
            records[kind].append({'source_ref': f'{kind}:{i}', 'contact_ids': ids,
                                  'derivation_contact_ids': derived[kind][i]['source_contact_ids'],
                                  'side': side, 'metrics': metrics})
    statistics = {}
    extras = {'contacts': PHASE_CODES + (RUN_CONTACT_CODES if mode == 'run' else ()),
              'steps': STEP_CODES + (RUN_STEP_CODES if mode == 'run' else ()),
              'cycles': ('toe_stride_length_m',)}
    for kind, codes in (('contacts', CONTACT_METRICS), ('steps', (*step_metrics, 'cadence_steps_per_min', 'step_time_percent')),
                        ('cycles', CYCLE_METRICS)):
        codes = tuple(dict.fromkeys((*codes, *extras[kind])))
        for code in codes:
            statistics[code] = {'record_kind': kind, **_statistics(records[kind], code)}
    return {'version': VERSION, 'starting_foot': starting_foot,
            'side_policy': summary.get('side_policy', 'legacy_contact_identity'),
            'identity_basis': 'manual_first_foot_and_reliable_alternation',
            'spatial_reference': 'contact_center' if mode == 'walk' else 'stable_toe_proxy',
            'toe_spatial_reference': 'stable_leading_edge; additive_to_existing_spatial_metrics',
            'measurement_basis': 'observed_certificates_and_explicit_model_estimates',
            'phase_percent_denominator': 'reference_foot_cycle_duration',
            'step_percent_denominator': 'same_foot_cycle_ending_at_arrival_contact',
            'sd_formula': 'population_n; unavailable_for_n_less_than_2',
            'si_formula': '100*abs(mean_left-mean_right)/((mean_left+mean_right)/2)',
            'difference_formula': 'mean_left-mean_right; percentage_metrics_use_percentage_points',
            'diff_formula': '100*(mean_left-mean_right)/mean_left; manual_screenshot_inference_v1',
            'derived_formulas': {**FORMULAS, 'toe_spatial_reference':
                'existing_certified_running_toe' if mode == 'run' else 'stable_optical_full_platform_leading_edge_v1'},
            'contact_phase_version': summary.get('contact_phases', {}).get('version'),
            'contact_phase_params': summary.get('contact_phases', {}).get('params', {}),
            'contact_phase_status': summary.get('contact_phases', {}).get('status'),
            'contact_phase_definition': summary.get('contact_phases', {}).get('definition'),
            'contact_percent_denominator': 'this_contact_duration',
            'minimum_comparison_samples_per_side': 3,
            'records': records, 'statistics': statistics}
