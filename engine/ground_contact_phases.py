"""Read-only optical subphases of an existing contact; never produces footfalls."""
from copy import deepcopy
from statistics import median

from engine.ground_metric_evidence import metric
from engine.ground_source_review import ownership_record, assigned_sources


VERSION = 'optical_contact_phases_v1'
PHASE_CODES = tuple(name + suffix for name in ('contact_phase', 'foot_flat', 'propulsive_phase')
                    for suffix in ('_s', '_percent'))


def _append(runs, start, end, islands, reason=None):
    row = [start, end, islands, reason]
    if runs and runs[-1][1] == start and runs[-1][2:] == row[2:]:
        runs[-1][1] = end
    else:
        runs.append(row)


class ContactShapeRecorder:
    """Sidecar histories keep detector objects and source certificates unchanged."""

    def __init__(self):
        self.streams = {}
        self.sources = {}
        self.groups = {}

    def _stream(self, candidate):
        # Keep the object alive so a discarded candidate's id cannot be reused.
        return self.streams.setdefault(id(candidate), (candidate, []))[1]

    def inherit(self, contact, candidate):
        if candidate is not None:
            self.streams[id(contact)] = (contact, deepcopy(self._stream(candidate)))

    def bind_source(self, source_id, candidate):
        self.sources.setdefault(source_id, self._stream(candidate))

    def observe(self, processor, frame, observation=None):
        raw = observation.frame if observation is not None else frame
        bad = set(processor.device.bad_indices)
        items = [*processor.active, *processor._narrow_candidates]

        def bounds(item):
            return (item['low'], item['high']) if isinstance(item, dict) else (item.low, item.high)

        def record(runs, low, high, shared=False):
            lo, hi = max(0, low - 1), min(len(raw.contact_bits), high + 2)
            reason = ('unobserved_shape' if any(i in bad or not raw.valid_bits[i] for i in range(lo, hi))
                      else 'shared_projection' if shared else None)
            islands = []
            for i in range(low, high + 1):
                if raw.contact_bits[i] and i not in bad and raw.valid_bits[i]:
                    if islands and islands[-1][1] + 1 == i:
                        islands[-1][1] = i
                    else:
                        islands.append([i, i])
            if islands and (islands[0][0] == 0 or islands[-1][1] == len(raw.contact_bits) - 1):
                reason = 'shape_clipped'
            _append(runs, frame.sample_index, frame.sample_index + 1, islands, reason)

        for candidate in items:
            low, high = bounds(candidate)
            shared = any(other is not candidate and low <= bounds(other)[1] and high >= bounds(other)[0]
                         for other in items)
            record(self._stream(candidate), low, high, shared)
        for group in processor._ownership_groups:
            if group['state'] == 'merged' or group['tracking_ended_sample'] is not None or not group['islands']:
                continue
            low = min(a for a, b in group['islands'])
            high = max(b for a, b in group['islands'])
            record(self.groups.setdefault(group['id'], []), low, high)

    def contact_runs(self, processor, contact, start, end):
        """Use final existing ownership decisions to attribute earlier observations."""
        samples, grouped = {}, {}

        def add(runs, target, until=end, override_reason=None):
            for a, b, islands, reason in runs:
                for n in range(max(start, a), min(end, b, until)):
                    sample = target.setdefault(n, [set(), None])
                    sample[0].update(i for lo, hi in islands for i in range(lo, hi + 1))
                    sample[1] = sample[1] or override_reason or reason

        add(self.streams.get(id(contact), (None, []))[1], samples)
        for group in processor._ownership_groups:
            owner = ownership_record(group)
            if group['state'] == 'merged' or not owner or owner['owner_id'] != contact.id:
                continue
            owned = assigned_sources(group)
            for source in group['sources']:
                if source['source_id'] in owned:
                    add(self.sources.get(source['source_id'], []), samples, source['joined_sample'])
            pending, seen = [group['id']], set()
            while pending:
                gid = pending.pop()
                if gid in seen:
                    continue
                seen.add(gid)
                add(self.groups.get(gid, []), grouped,
                    override_reason=None if len(owned) == len(group['sources']) else 'shared_projection')
                pending.extend(processor._ownership_groups[gid].get('merged_group_ids', []))
        samples.update(grouped)
        result = []
        for n in range(start, end):
            indices, reason = samples.get(n, (set(), 'shape_not_recorded'))
            islands = []
            for i in sorted(indices):
                if islands and islands[-1][1] + 1 == i:
                    islands[-1][1] = i
                else:
                    islands.append([i, i])
            _append(result, n, n + 1, islands, reason)
        return result


def analyse_contact_phases(contact, runs, positions, direction, params):
    """IC is any initial foot contact. The last sustained rear exit wins."""
    result = {code: metric(reason='no_stable_platform') for code in PHASE_CODES}
    output = {'contact_id': contact['id'], 'metrics': result, 'boundaries': {},
              'toe_m': metric(reason='no_stable_platform'), 'shape_runs': runs,
              'interpretation': 'optical_estimate_not_validated_anatomical_events'}
    if not direction:
        for code in result:
            result[code] = metric(reason='direction_unknown')
        output['toe_m'] = metric(reason='direction_unknown')
        return output
    rows = []
    for start, end, islands, reason in runs:
        if reason or not islands:
            rows.append((start, end, None))
            continue
        points = [direction * positions[i] for lo, hi in islands for i in range(lo, hi + 1)]
        rows.append((start, end, (min(points), max(points), len(points))))
    tolerance = params['edge_stability_m']

    def similar(a, b):
        return (a is not None and b is not None and abs(a[0] - b[0]) <= tolerance + 1e-9
                and abs(a[1] - b[1]) <= tolerance + 1e-9
                and abs(a[2] - b[2]) <= params['count_tolerance'])

    platforms = []
    for i, (start, end, shape) in enumerate(rows):
        if shape is None or (i and rows[i-1][1] == start and rows[i-1][2] == shape):
            continue
        stop = end
        counts = [(shape[2], end-start)]
        for a, b, next_shape in rows[i+1:]:
            if a != stop or not similar(shape, next_shape):
                break
            stop = b
            counts.append((next_shape[2], b-a))
        if stop - start >= params['flat_confirm_ms']:
            cumulative = 0
            for count, duration in sorted(counts):
                cumulative += duration
                if cumulative * 2 >= stop - start:
                    break
            platforms.append((start, stop, (shape[0], shape[1], count), i))
    if not platforms:
        return output
    max_width = max(shape[1] - shape[0] for _, _, shape, _ in platforms)
    max_count = max(p[2][2] for p in platforms)
    full = [p for p in platforms if p[2][1] - p[2][0] >= max_width - params['platform_extent_tolerance_m'] - 1e-9
            and p[2][2] >= max_count - params['count_tolerance']]
    if not full:
        return output
    first = full[0]
    # The onset may precede a one-beam expansion. Keep the final full reference
    # fixed so a slow rear retreat is not absorbed into a moving baseline.
    reference_width = max(p[2][1] - p[2][0] for p in full)
    last = next(p for p in reversed(full) if p[2][1] - p[2][0] >= reference_width - tolerance - 1e-9)
    # Retain the first full platform but use the final settled position after sliding.
    flat, _, _, flat_index = first
    rear, front, count = last[2]
    output['toe_m'] = metric(front * direction)
    start = contact.get('touch_sample')
    end = contact.get('lift_sample')
    flat_reason = ('touch_not_observed' if start is None else 'platform_boundary_unobserved'
                   if flat > start and (flat_index == 0 or rows[flat_index-1][2] is None) else None)
    if flat_reason is None:
        output['boundaries']['platform_start'] = {'sample': flat,
            'confirmed_sample': flat + params['flat_confirm_ms'] - 1}
        result['contact_phase_s'] = metric((flat - start) / 1000)
    else:
        result['contact_phase_s'] = metric(reason=flat_reason)
    exit_start = confirmed = None
    candidate = None
    candidate_end = None
    maximum_retreat = 0.
    candidate_known = False
    for index in range(last[3], len(rows)):
        a, b, shape = rows[index]
        if shape is None:
            candidate = candidate_end = exit_start = confirmed = None
            maximum_retreat = 0.
            continue
        retreat = shape[0] - rear
        if retreat <= tolerance + 1e-9:
            candidate = candidate_end = exit_start = confirmed = None
            maximum_retreat = 0.
            continue
        if exit_start is not None:
            continue
        if abs(shape[1] - front) > tolerance + 1e-9 or shape[2] >= count:
            candidate = candidate_end = None
            maximum_retreat = 0.
            continue
        if candidate is None or candidate_end != a:
            candidate, maximum_retreat = a, 0.
            candidate_known = (index > 0 and rows[index-1][1] == a and rows[index-1][2] is not None
                               and rows[index-1][2][0] - rear <= tolerance + 1e-9)
        candidate_end = b
        maximum_retreat = max(maximum_retreat, retreat)
        if candidate_known and b - candidate >= params['heel_confirm_ms'] and maximum_retreat + 1e-9 >= params['heel_retreat_m']:
            exit_start = candidate
            confirmed = max(a, candidate + params['heel_confirm_ms'] - 1)
    if exit_start is not None:
        output['boundaries']['rear_exit_start'] = {'sample': exit_start, 'confirmed_sample': confirmed}
        result['foot_flat_s'] = metric((exit_start - flat) / 1000, flat_reason)
        result['propulsive_phase_s'] = metric((end - exit_start) / 1000 if end is not None else None,
                                             None if end is not None else 'lift_not_observed')
    else:
        result['foot_flat_s'] = metric(reason='no_sustained_rear_exit')
        result['propulsive_phase_s'] = metric(reason='no_sustained_rear_exit')
    duration = contact.get('contact_s', {})
    denominator = duration.get('value') if duration.get('valid') else None
    for name in ('contact_phase', 'foot_flat', 'propulsive_phase'):
        item = result[name + '_s']
        result[name + '_percent'] = metric(100 * item['value'] / denominator
            if item['valid'] and denominator and denominator > 0 else None,
            item['missing_reason'] or (None if denominator and denominator > 0 else 'incomplete_contact'))
    return output


def build_contact_phases(processor, summary, mode):
    pitch = median(s.pitch_m for s in processor.device.layout.segments)
    params = {'flat_confirm_ms': 5, 'heel_confirm_ms': 3, 'edge_stability_m': pitch / 2,
              'heel_retreat_m': 2 * pitch, 'platform_extent_tolerance_m': 2 * pitch, 'count_tolerance': 1}
    direction = processor.direction
    basis = 'processor_direction'
    if not direction:
        from config.footfall_events import active_touch_events
        points = [summary.get('landing_positions_m', {}).get(str(e['contact_id']))
                  for e in active_touch_events(summary.get('event_publications', []))]
        points = [x for x in points if x is not None]
        deltas = [b-a for a, b in zip(points, points[1:]) if abs(b-a) >= .15]
        if deltas and (all(x > 0 for x in deltas) or all(x < 0 for x in deltas)):
            direction = 1 if deltas[0] > 0 else -1
            basis = 'published_landing_progression'
    results = []
    for contact, row in zip(processor.contacts, summary['contacts']):
        if not processor._touch_events.get(contact.id, {}).get('active'):
            continue
        start = round(contact.start * 1000) if mode == 'walk' else int(contact.start)
        stop = contact.end
        if stop is None:
            continue
        end = round(stop * 1000) if mode == 'walk' else int(stop)
        runs = processor._shape_recorder.contact_runs(processor, contact, start, end)
        result = analyse_contact_phases(row, runs, processor.positions, direction, params)
        event = processor._touch_events[contact.id]
        result.update(event_id=event['event_id'], event_revision=event.get('revision', 1),
                      evidence_available_sample=processor.last_sample)
        results.append(result)
    return {'version': VERSION, 'params': params, 'status': 'prototype_pending_boundary_validation',
            'direction': direction, 'direction_basis': basis,
            'definition': 'any_initial_contact_to_platform_to_final_sustained_rear_exit_to_final_contact',
            'contacts': results}
