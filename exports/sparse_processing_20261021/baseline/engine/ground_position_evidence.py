"""Spatial evidence for existing ground contacts; no ownership or temporal mutation."""
from statistics import median

from engine.ground_source_review import ownership_record, assigned_sources
from engine.ground_metric_evidence import group_release_evidence


def running_position_history(p, c):
    evidence = {'rule_version': 'complete_owned_toe_history_v1', 'valid': False,
                'missing_reason': 'no_owned_group', 'window': [c.start, c.end]}
    groups = [g for g in p._ownership_groups if (ownership_record(g) or {}).get('owner_id') == c.id]
    if len(groups) != 1:
        return [], evidence
    g = groups[0]
    evidence['group_id'] = g['id']
    evidence['source_ids'] = sorted(assigned_sources(g))
    release = group_release_evidence(p._ownership_groups, c.id)
    if not release['occupancy_valid'] or release['missing_reason']:
        evidence['missing_reason'] = release['missing_reason'] or 'incomplete_observation'
        return [], evidence
    if c.interrupted or c.first_masked_sample is not None:
        evidence['missing_reason'] = c.interrupted or 'masked_contact_boundary'
        return [], evidence
    if c.end != g['occupancy_end_sample'] or c.start != ownership_record(g)['original_touch_sample']:
        evidence['missing_reason'] = 'incomplete_spatial_window'
        return [], evidence
    start_sample, end_sample = int(c.start), int(c.end)
    if (start_sample, end_sample) != (c.start, c.end):
        evidence['missing_reason'] = 'incomplete_spatial_window'
        return [], evidence
    bad_indices = set(p.device.bad_indices) | set(p.device.layout.invalid_bit_indices)
    samples = {}
    invalid = set()

    def add(start, end, islands, reliable, source):
        for n in range(max(int(start), start_sample), min(int(end), end_sample)):
            if (not reliable or not islands or any(
                    lo == 0 or hi == len(p.positions) - 1
                    or any(lo - 1 <= i <= hi + 1 for i in bad_indices)
                    for lo, hi in islands)):
                invalid.add(n)
                continue
            row = samples.setdefault(n, [[], set()])
            row[0].extend(islands)
            row[1].add(source)

    for a, b, lo, hi in c.edges:
        add(a, b, [(lo, hi)], True, 'contact')
    for s in g['sources']:
        for a, b, lo, hi in s['evidence_at_join'].get('edges', []):
            healthy = any(x <= a and b <= y for x, y in s['valid_sample_intervals'])
            add(a, b, [(lo, hi)], healthy, 'source:' + str(s['source_id']))
    for a, b, islands, reliable in g['observation_runs']:
        add(a, b, islands, reliable, 'group:' + str(g['id']))
    missing = [n for n in range(start_sample, end_sample) if n not in samples or n in invalid]
    if missing:
        evidence['missing_reason'] = 'incomplete_spatial_window'
        evidence['missing_samples'] = missing
        return [], evidence
    edges, provenance = [], []
    for n in range(start_sample, end_sample):
        islands, sources = samples[n]
        low = min(x[0] for x in islands); high = max(x[1] for x in islands)
        if any(low - 1 <= i <= high + 1 for i in bad_indices):
            evidence['missing_reason'] = 'unknown_inside_spatial_envelope'
            return [], evidence
        if edges and edges[-1][1] == n and edges[-1][2:] == [low, high]:
            edges[-1][1] = n + 1
        else:
            edges.append([n, n + 1, low, high])
        sources = sorted(sources)
        if provenance and provenance[-1][1] == n and provenance[-1][2] == sources:
            provenance[-1][1] = n + 1
        else:
            provenance.append([n, n + 1, sources])
    record = ownership_record(g)
    evidence.update(valid=True, missing_reason=None, unique_samples=c.end-c.start,
                    evidence_available_sample=max(g['tracking_ended_sample'], record['recovered_sample'],
                        record.get('established_sample', record['recovered_sample']),
                        *[d['decided_sample'] for d in g.get('source_decisions', []) if d['outcome']=='associated']),
                    evaluated_sample=p.last_sample,
                    observation_sources=provenance)
    return edges, evidence


def record_centre_sample(samples, frame, low, high, bad_indices, observation=None):
    n = frame.sample_index
    if (len(samples) >= 100 or samples and (n % 20 or samples[-1][0] == n)):
        return
    unknown = [i for i in range(low, high+1) if not frame.valid_bits[i] or i in bad_indices]
    if observation is not None and not observation.reliable(low, high):
        unknown = list(range(low, high+1))
    samples.append([n, low, high, unknown])


def walking_centre_position(p, c):
    start = round(c.start * 1000)
    end = round(c.end * 1000) if c.end is not None else None
    evidence = {'rule_version': 'owned_sparse_centre_v1', 'valid': False,
                'window': [start, end], 'missing_reason': 'incomplete_contact'}
    if not c.confirmed or end is None or 'touch' in c.edge_estimates or 'lift' in c.edge_estimates:
        return None, evidence
    if c.exclusion not in {None, 'unresolved_fragment_join', 'unresolved_coalescence', 'masked_contact_boundary'}:
        evidence['missing_reason'] = c.exclusion
        return None, evidence
    groups = [g for g in p._ownership_groups if (ownership_record(g) or {}).get('owner_id') == c.id]
    if len(groups) != 1:
        evidence['missing_reason'] = c.exclusion or 'no_owned_group'
        return None, evidence
    g = groups[0]; record = ownership_record(g)
    evidence.update(group_id=g['id'], source_ids=sorted(assigned_sources(g)))
    if assigned_sources(g) != {s['source_id'] for s in g['sources']}:
        evidence['missing_reason'] = 'unresolved_position_source'
        return None, evidence
    if (g['tracking_end_reason'] != 'reliable_clear' or g['occupancy_end_sample'] != end
            or record['original_touch_sample'] != start):
        return None, evidence
    if g['valid_sample_intervals'] != [[start,end]] or any(not r[3] for r in g['observation_runs']):
        evidence['missing_reason'] = 'incomplete_spatial_observation'
        return None, evidence
    observed_intervals = [r[:2] for r in g['observation_runs']]
    observed_intervals += [interval for s in g['sources'] for interval in s['valid_sample_intervals']]
    if p._union_sample_intervals(observed_intervals) != [[start,end]]:
        evidence['missing_reason'] = 'incomplete_spatial_observation'
        return None, evidence
    # The existing birth sample plus the original 20 ms grid, capped at 100.
    required = sorted({start, *range((start + 19)//20*20, min(end,start+2000), 20)})[:100]
    samples = {n: [] for n in required}
    for s in g['sources']:
        for n,lo,hi,unknown in s['evidence_at_join'].get('position_samples', []):
            if n in samples and n < s['joined_sample']:
                samples[n].append((lo,hi,unknown,'source:' + str(s['source_id'])))
    for a,b,islands,reliable in g['observation_runs']:
        for n in required:
            if a <= n < b:
                for lo,hi in islands:
                    samples[n].append((lo,hi,[], 'group:' + str(g['id'])))
    bad = set(p.device.bad_indices) | set(p.device.layout.invalid_bit_indices)
    inputs = []
    for n in required:
        observations = samples[n]
        if not observations:
            evidence.update(missing_reason='missing_centre_sample', rejected_sample=n)
            return None, evidence
        low = min(r[0] for r in observations); high = max(r[1] for r in observations)
        unknown = {i for _,_,xs,_ in observations for i in xs} | {i for i in bad if low<=i<=high}
        if (low == 0 or high == len(p.positions)-1 or low in unknown or high in unknown
                or unknown - bad or p.positions[high]-p.positions[low] > .45):
            evidence.update(missing_reason='unknown_position_boundary', rejected_sample=n)
            return None, evidence
        # Interior bad beams remain unknown; only owned healthy outer bounds define the centre.
        inputs.append({'sample':n, 'low':low, 'high':high,
                       'centre_m':(p.positions[low]+p.positions[high])/2,
                       'sources':sorted({r[3] for r in observations}), 'unknown_indices':sorted(unknown)})
    if c.exclusion == 'masked_contact_boundary' and not any(r['unknown_indices'] for r in inputs):
        evidence['missing_reason'] = c.exclusion
        return None, evidence
    values = [r['centre_m'] for r in inputs]
    ordered = sorted(values)
    spread = ordered[3*len(ordered)//4]-ordered[len(ordered)//4]
    evidence.update(inputs=inputs, sample_count=len(inputs), interquartile_spread_m=spread,
                    stability_limit_m=.18)
    if (len(values) < 2 or spread > .18 + 1e-9
            or any(abs(b-a) > .18 + 1e-9 for a,b in zip(values,values[1:]))):
        evidence['missing_reason'] = 'unstable_representative_centre'
        return None, evidence
    evidence.update(valid=True, missing_reason=None, sampling_ms=20, max_samples=100,
                    evidence_available_sample=max(g['tracking_ended_sample'],record['recovered_sample'],
                        record.get('established_sample',record['recovered_sample']),
                        *[d['decided_sample'] for d in g.get('source_decisions',[]) if d['outcome']=='associated']),
                    evaluated_sample=p.last_sample)
    return median(values), evidence
