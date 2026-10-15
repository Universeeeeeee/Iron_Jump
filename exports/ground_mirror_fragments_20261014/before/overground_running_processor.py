"""Optical overground running, device-clock timing and toe-to-toe geometry.

A blocked beam is an optical proxy, not a measurement of ground reaction force.
Unobserved events never become zeros; only unresolved candidates block gait relationships.
"""
from dataclasses import asdict, dataclass, field
from copy import deepcopy
from collections import deque

from engine.ground_source_review import (SHORT_ISLAND_MS, ownership_record, assigned_sources,
    observe_review_frame, review_group_sources)

from engine.ground_metric_evidence import METRIC_POLICY, group_release_evidence, metric
from engine.ground_position_evidence import running_position_history
from config.overground_running_report import OvergroundRunningReport
from hardware.sensor_frame import blocked_indices



@dataclass
class Contact:
    id: int
    epoch: int
    label: str
    side: str
    start: float
    last: int
    low: int
    high: int
    touch_known: bool
    end: float | None = None
    lift_known: bool = False
    confirmed: bool = False
    problem: str | None = None
    interrupted: str | None = None
    first_uncertain_sample: int | None = None
    first_masked_sample: int | None = None
    # Run-length encoded leading edges; unchanged stances take constant space.
    edges: list = field(default_factory=list)
    endpoint_run: int = 0
    observed_samples: int = 0
    absent_samples: int = 0
    release_start: float | None = None
    edge_estimates: dict = field(default_factory=dict)
    has_unknown: bool = False
    candidate_since: int | None = None
    last_reliable_sample: int | None = None
    first_seen_sample: int | None = None
    confirmed_sample: int | None = None
    candidate_outcome: str = "pending"
    isolated_clear: bool = False
    clear_before_candidate: int | None = None
    peak_width_m: float = 0.0
    source_islands: tuple = ()
    valid_sample_intervals: list = field(default_factory=list)
    ownership_source_id: int | None = None
    ownership_unresolved_since: int | None = None
    ownership_competition: list = field(default_factory=list)
    observation_wait_since: int | None = None
    observation_closed_sample: int | None = None


class OvergroundRunningProcessor:
    OWNERSHIP_OBSERVATION_BUDGET_MS = 2000
    name = "overground_running"
    display_mode = "地面跑步"
    DIRECTION_DISPLACEMENT_M = .15
    CLUSTER_GAP_M = .04
    MATCH_MARGIN_M = .035
    MAX_CLUSTER_WIDTH_M = .45
    NARROW_CANDIDATE_WIDTH_M = .03

    def __init__(self, config, device):
        self.config, self.device = config, device
        self.positions = device.layout.positions_m
        self.contacts, self.active, self.issues, self.timeline = [], [], [], []
        self._preserved_stops = []
        self.phases = []  # [start, exclusive end, occupancy, epoch]
        self.epoch = 0
        self.origin = None
        self.last_sample = device.checked_sample_index
        self.last_time = None
        self.last_occupied = None
        self.direction = 0
        self._direction_positions = {}
        self._direction_pairs = set()
        self._direction_last_touch = None
        self.finished_reason = None
        self._identity_known = True
        self._recovering = False
        self._masked_contact_uncertain = False
        self._last_label = "B"
        self._clear_since = None
        self._exit_evidence = False
        self._exit_contact_id = None
        self._ambiguous = False
        self._last_visual = -100
        self._phase_adjustments = []
        self._duration_censored = False
        self._duration_start_censored = False
        self._duration_start_unknown_from = None
        self._duration_clear_upper = None
        self._narrow_candidates = []
        self._narrow_unknown = []
        self._narrow_barriers = []
        self._exit_blocked_through_id = -1
        self._previous_frame = None
        self._candidate_decisions = []
        self._commit_cursor = 0
        self._suspended_exit = None
        self._local_regions = []
        self._multiple_islands_now = False
        self._ownership_groups = []
        self._source_review_frames = deque(maxlen=SHORT_ISLAND_MS + 1)
        self._next_ownership_source = 0
        self._touch_events = {}
        self.event_audit = []
        self._committed_contacts = set()
        self._publication_closed = False
        self._split_ambiguous = set()

    OWNERSHIP_RULE_VERSION = 'early_local_growth_v1'

    @property
    def touch_events(self):
        return [dict(e) for e in self._touch_events.values()]

    @property
    def reliable_touch_count(self):
        return sum(e['active'] for e in self._touch_events.values())

    def _sync_touch_publications(self):
        self._review_contact_competition()
        # A later shape ambiguity censors shape/lift, not a published landing.
        # Only an explicit event reclassification retracts that landing.
        for c in self.contacts:
            event = self._touch_events.get(c.id)
            correction = c.candidate_outcome in {'excluded_nonstep', 'associated_fragment'}
            if event is not None:
                if event['active'] and correction:
                    previous = event['revision']
                    event.update(active=False, revision=previous + 1)
                    c.touch_known = False
                    for later in self.contacts:
                        if later.epoch != c.epoch or (later.start, later.id) < (c.start, c.id):
                            continue
                        self._committed_contacts.discard(later.id)
                        if later.label:
                            prior_event = self._touch_events[later.id]
                            self.event_audit.append({'action': 'sequence_retracted',
                                'event_id': prior_event['event_id'], 'sample': self.last_sample,
                                'touch_sample': prior_event['touch_sample'], 'label': later.label,
                                'reason': 'earlier_event_retracted', 'corrected_event_id': event['event_id']})
                            later.label, later.side = '', 'unknown'
                    self._identity_known = False
                    self.event_audit.append({**event, 'action': 'retract',
                        'sample': self.last_sample, 'reason': c.candidate_outcome,
                        'replaces_revision': previous})
                if event['active']:
                    c.touch_known = True
                continue
            problem = getattr(c, 'exclusion', None) or getattr(c, 'problem', None)
            if (not c.confirmed or not c.touch_known or correction or self._contact_competition_pending(c)
                    or problem in {'simultaneous_contacts', 'unresolved_coalescence',
                                   'unresolved_multiple_islands', 'unknown_touch_after_gap'}):
                continue
            if (self._temporal_problem(c, c.start) is not None
                    and not any(g.get('recovery', {}).get('owner_id') == c.id for g in self._ownership_groups)):
                continue
            event = {'event_id': f'{self.device.stream_id}:{c.epoch}:{c.id}',
                     'contact_id': c.id, 'epoch': c.epoch, 'touch_sample': self._event_sample(c),
                     'touch_bounds': c.edge_estimates.get('touch'),
                     'published_sample': self.last_sample, 'active': True, 'revision': 1,
                     'publication_version': 'reliable_touch_before_sequence_v1'}
            self._touch_events[c.id] = event
            recovery = next((g for g in self._ownership_groups
                             if g.get('recovery', {}).get('owner_id') == c.id), None)
            self.event_audit.append({**event, 'action': 'publish', 'sample': self.last_sample,
                'reason': 'conditional_ownership_recovery' if recovery else 'independent_contact_confirmation',
                'group_id': recovery['id'] if recovery else None})

    def _pending_group_before(self, c):
        return any(g['epoch'] == c.epoch and g['state'] == 'observing'
                   and any(source['source_id'] not in assigned_sources(g)
                           and (source['first_sample'] if source['first_sample'] is not None
                                else g['unresolved_since_sample']) <= self._event_sample(c)
                           for source in g['sources'])
                   for g in self._ownership_groups)

    def _ownership_barriers(self):
        # Unknown landings block relationships crossing their original onset;
        # their later occupied tail does not invalidate a new remote sequence.
        barriers = [(c.start, c.start + 1, c.epoch) for c in self.contacts
                    if self._contact_competition_pending(c)]
        for g in self._ownership_groups:
            if g['state'] == 'merged':
                continue
            recovered = assigned_sources(g)
            for source in g['sources']:
                if source['source_id'] in recovered or source['evidence_at_join'].get('confirmed'):
                    continue
                start = source['first_sample']
                if start is None:
                    start = g['unresolved_since_sample']
                barriers.append((start, start + 1, g['epoch']))
        return barriers

    @staticmethod
    def _contact_competition_pending(c):
        # Publication and metric veto: final unknown attribution is still unsafe.
        return (c.candidate_outcome not in {'associated_fragment', 'excluded_nonstep'}
                and any(r['outcome'] in {'pending', 'unresolved'} for r in c.ownership_competition))

    @staticmethod
    def _contact_competition_waiting(c):
        # Ordering waits only while more attribution evidence is being considered.
        return (c.candidate_outcome not in {'associated_fragment', 'excluded_nonstep'}
                and any(r['outcome'] == 'pending' for r in c.ownership_competition))

    def _review_contact_competition(self):
        # Formal observations can create an ordinary Contact where the raw
        # path would defer a narrow candidate. Both must retain the same gate.
        live = [g for g in self._ownership_groups if g['tracking_ended_sample'] is None]
        for c in self.contacts:
            if (not self._touch_events.get(c.id, {}).get('active')
                    and c.candidate_outcome not in {'associated_fragment', 'excluded_nonstep'}
                    and c in self.active and c.peak_width_m < self.NARROW_CANDIDATE_WIDTH_M):
                for g in live:
                    if (g['epoch'] != c.epoch or any(s['source_id'] == c.ownership_source_id for s in g['sources'])
                            or any(r['group_id'] == g['id'] for r in c.ownership_competition)
                            or any(lo <= c.high and hi >= c.low for lo, hi in g['islands'])
                            or not any(self.positions[c.low] <= self.positions[hi] + self.MATCH_MARGIN_M
                                       and self.positions[c.high] >= self.positions[lo] - self.MATCH_MARGIN_M
                                       for lo, hi in g['islands'])):
                        continue
                    self._ownership_source(c)
                    row = {'group_id': g['id'], 'source_id': c.ownership_source_id,
                           'detected_sample': self.last_sample, 'evidence_start_sample': c.start,
                           'outcome': 'pending', 'rule_version': 'existing_narrow_competition_gate_v1',
                           'reason': 'nearby_unresolved_group_source'}
                    c.ownership_competition.append(row)
                    self.event_audit.append({'action': 'contact_competition', 'sample': self.last_sample,
                                            'contact_id': c.id, **deepcopy(row)})
            for row in c.ownership_competition:
                if row['outcome'] in {'associated', 'independent'}:
                    continue
                g = self._ownership_groups[row['group_id']]
                while g['state'] == 'merged':
                    g = self._ownership_groups[g['merged_into']]
                if c.ownership_source_id in assigned_sources(g):
                    row.update(outcome='associated', reason='existing_group_attribution')
                elif row['outcome'] != 'pending':
                    continue
                elif (c.confirmed and c.touch_known and not c.problem and not c.interrupted
                      and not c.has_unknown and not c.edge_estimates
                      and c.peak_width_m >= self.NARROW_CANDIDATE_WIDTH_M
                      and c.valid_sample_intervals == [[c.start, c.last + 1]]):
                    row.update(outcome='independent', reason='existing_independent_growth_gate')
                elif c.end is not None or c.interrupted or self.last_sample-min(r['detected_sample'] for r in c.ownership_competition) >= self.OWNERSHIP_OBSERVATION_BUDGET_MS:
                    row.update(outcome='unresolved', reason=c.interrupted or ('reliable_clear' if c.end is not None else 'observation_budget'))
                else:
                    continue
                row.update(decided_sample=self.last_sample,
                           valid_sample_intervals=deepcopy(c.valid_sample_intervals),
                           peak_width_m=c.peak_width_m)
                self.event_audit.append({'action': 'contact_competition', 'sample': self.last_sample,
                                        'contact_id': c.id, **deepcopy(row)})

    def _ownership_rule(self, group):
        sources, runs = group['sources'], group['observation_runs']
        if any(s['evidence_at_join'].get('observation_closed_sample') is not None for s in sources):
            return 'observation_budget'
        window = max(self.config.min_contact_time, self.config.confirmation_ms)
        if any(s['first_sample'] is None for s in sources):
            return 'unknown_original_time'
        first = min(s['first_sample'] for s in sources)
        evidence = [s['evidence_at_join'] for s in sources]
        if sum(bool(e.get('confirmed')) for e in evidence) == 1:
            return 'late_source_review_required'
        if any(e.get('confirmed') or s['observed_samples'] >= window for s,e in zip(sources,evidence)):
            return 'independent_mature_source'
        if sum(e.get('peak_width_m', 0) >= .08 for e in evidence) > 1:
            return 'competing_wide_sources'
        if any(s['joined_sample'] - first > window for s in sources):
            return 'prolonged_separate_sources'
        allowed = {None, 'simultaneous_contacts', 'unresolved_multiple_islands'}
        if any(e.get('problem') not in allowed or e.get('exclusion') not in allowed
               or e.get('masked_contact') or e.get('has_unknown') or e.get('merged_interruptions')
               or e.get('edge_estimates') or e.get('clear_gaps') for e in evidence):
            return 'uncertain_source_history'
        if any(s['valid_sample_intervals'] != [[s['first_sample'], s['last_sample'] + 1]]
               for s in sources):
            return 'unreliable_source_samples'
        if any(e.get('peak_width_m', 0) > self.positions[e['high']] - self.positions[e['low']]
               + max(self.device.layout.segments[e['low'] // 96].pitch_m,
                     self.device.layout.segments[e['high'] // 96].pitch_m) + 1e-9
               for e in evidence):
            return 'source_shrank_before_join'
        intervals = group['valid_sample_intervals']
        if intervals != [[first, group['last_sample'] + 1]] or any(not r[3] for r in runs):
            return 'discontinuous_observation'
        if not runs or any(len(r[2]) != 1 for r in runs):
            return 'separate_projection'
        widths = [self.positions[r[2][0][1]] - self.positions[r[2][0][0]] for r in runs]
        if any(r[2][0][0] == 0 or r[2][0][1] == len(self.positions)-1 for r in runs):
            return 'boundary_projection'
        if max(widths) > .45 or any(abs(b-a) > .18 for a,b in zip(widths,widths[1:])):
            return 'incompatible_projection'
        if max(widths) < .08 or max(widths) - widths[0] < .04:
            return 'insufficient_growth'
        if (group['observed_samples'] < window
                or group['last_sample'] - runs[0][0] + 1 < max(10, self.config.confirmation_ms)):
            return 'awaiting_continuous_growth'
        return None

    def _recover_ownership_groups(self):
        self._review_contact_competition()
        for group in self._ownership_groups:
            review_group_sources(self, group)
            recovery = ownership_record(group)
            if recovery is not None:
                # Later new sources can compete with attribution of occupancy;
                # they do not automatically negate the earlier landing.
                if assigned_sources(group) != {s['source_id'] for s in group['sources']}:
                    if 'post_recovery_ambiguity_sample' not in group:
                        group['post_recovery_ambiguity_sample'] = self.last_sample
                        self.event_audit.append({'action': 'ownership_competing_source',
                            'sample': self.last_sample, 'group_id': group['id'],
                            'original_owner_id': recovery['owner_id'],
                            'new_source_ids': sorted({s['source_id'] for s in group['sources']}
                                                     - assigned_sources(group))})
                    continue
                if group['tracking_ended_sample'] in (None, self.last_sample):
                    self._update_recovered_owner(group)
                continue
            if group['state'] != 'observing':
                continue
            reason = self._ownership_rule(group)
            checks = group.setdefault('recovery_evaluations', [])
            if not checks or checks[-1]['reason'] != reason:
                checks.append({'sample': self.last_sample, 'reason': reason,
                               'rule_version': self.OWNERSHIP_RULE_VERSION})
            if reason is not None:
                continue
            first = min(s['first_sample'] for s in group['sources'])
            source_ids = {s['source_id'] for s in group['sources']}
            members = [c for c in self.contacts if c.ownership_source_id in source_ids]
            owner = next((c for c in members if self._event_sample(c) == first), None)
            if owner is None:
                owner = self._new_recovered_owner(group, first)
                self.contacts.append(owner)
                self.active.append(owner)
            for c in members:
                if c is not owner:
                    c.candidate_outcome = 'associated_fragment'
                    if c in self.active:
                        self.active.remove(c)
            owner.ownership_source_id = min(group['sources'], key=lambda s: s['first_sample'])['source_id']
            owner.ownership_unresolved_since = group['unresolved_since_sample']
            group['recovery'] = {'rule_version': self.OWNERSHIP_RULE_VERSION,
                'recovered_sample': self.last_sample, 'original_touch_sample': first,
                'owner_id': owner.id, 'source_ids': sorted(source_ids),
                'valid_sample_intervals': deepcopy(group['valid_sample_intervals']),
                'unique_samples': group['observed_samples'],
                'budget_start_sample': group['unresolved_since_sample'],
                'growth_m': max(self.positions[r[2][0][1]] - self.positions[r[2][0][0]]
                                for r in group['observation_runs'])
                    - (self.positions[group['observation_runs'][0][2][0][1]]
                       - self.positions[group['observation_runs'][0][2][0][0]]),
                'early_window_ms': max(self.config.min_contact_time, self.config.confirmation_ms),
                'other_occupied_contacts': [c.id for c in self.active if c not in members and c is not owner
                                           and c.confirmed and c.touch_known and not c.has_unknown
                                           and not getattr(c, 'problem', None)
                                           and not getattr(c, 'exclusion', None)
                                           and not getattr(c, 'interrupted', None)],
                'interpretation': 'conditional_local_growth_not_optical_identity_proof'}
            self._update_recovered_owner(group)
            self.event_audit.append({'action': 'ownership_recovered', 'sample': self.last_sample,
                                    'group_id': group['id'], **deepcopy(group['recovery'])})

    def _event_sample(self, c):
        return c.start

    def _new_recovered_owner(self, group, first):
        low, high = group['islands'][0]
        return Contact(len(self.contacts), self.epoch, '', 'unknown', first,
                       group['last_sample'], low, high, True, first_seen_sample=first)

    def _update_recovered_owner(self, group):
        record = ownership_record(group)
        owner = self.contacts[record['owner_id']]
        if owner.candidate_outcome in {'excluded_nonstep', 'associated_fragment'}:
            return
        owner.confirmed = owner.touch_known = True
        owner.candidate_outcome = 'confirmed_contact'
        if owner.confirmed_sample is None or not self._touch_events.get(owner.id, {}).get('active'):
            owner.confirmed_sample = record['recovered_sample']
        owner.observed_samples = group['observed_samples']
        owner.valid_sample_intervals = deepcopy(group['valid_sample_intervals'])
        owner.problem = 'unresolved_fragment_join'
        if owner.first_uncertain_sample is None or not self._touch_events.get(owner.id, {}).get('active'):
            owner.first_uncertain_sample = record['recovered_sample']
        owner.has_unknown = True
        owner.last = group['last_sample']
        if self.origin is None:
            self.origin = owner.start / 1000
        for region in self._local_regions:
            if region.get('ownership_group_id') == group['id']:
                region['members'] = [owner]
                region['private'] = True
        if group['occupancy_end_sample'] is not None:
            owner.end, owner.lift_known = group['occupancy_end_sample'], False
            if owner in self.active:
                self.active.remove(owner)

    def break_continuity(self, code, frame_index=None):
        self._close_ownership_groups(code, self.last_sample)
        self._preserved_stops = self._stop_intervals()
        self.issues.append({"code": code, "sample": self.last_sample, "frame_index": frame_index})
        if self.origin is not None:
            self.timeline.append({"timestamp_s": (self.last_sample + 1) / 1000 - self.origin,
                                  "positions_m": self.positions, "contact_bits": [0] * len(self.positions),
                                  "valid_bits": [0] * len(self.positions), "feet": [], "quality_flags": [code]})
        for c in self.active:
            self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
            if not c.confirmed and c.candidate_outcome == "pending":
                c.candidate_outcome = "unresolved"
                self._record_candidate(c, "unresolved", code)
            c.interrupted = code
        self.active.clear()
        self.epoch += 1
        self._identity_known = False
        self._recovering = True
        self._last_label = "B"
        self._clear_since = None
        self._exit_evidence = False
        self._exit_contact_id = None
        for p in self._narrow_candidates:
            self._mark_unknown_start(p['start'])
            self._narrow_unknown.append((p['start'], p['last'] + 1, self.epoch - 1))
            self._record_candidate(p, 'unresolved', code)
        self._narrow_candidates.clear()
        self._previous_frame = None
        self._suspended_exit = None
        self._local_regions.clear()

    def _mark_unknown_start(self, sample, touch_bounds=None):
        if self.origin is None:
            if touch_bounds is not None:
                sample = touch_bounds[0]
            self._duration_start_censored = True
            if self._duration_start_unknown_from is None or sample < self._duration_start_unknown_from:
                self._duration_start_unknown_from = sample

    def _local_clear(self, frame, low, high):
        if frame is None:
            return False
        left = self.positions[low] - self.MATCH_MARGIN_M
        right = self.positions[high] + self.MATCH_MARGIN_M
        if left < self.positions[0] or right > self.positions[-1]:
            return False
        indices = [i for i, pos in enumerate(self.positions) if left <= pos <= right]
        return (not any(i in self.device.bad_indices for i in indices)
                and all(frame.valid_bits[i] and not frame.contact_bits[i] for i in indices))

    def _candidate_row(self, candidate, outcome, reason, closed_sample=None, owner_id=None):
        if isinstance(candidate, Contact):
            row = {"source": "contact", "contact_id": candidate.id, "epoch": candidate.epoch,
                   "first_sample": candidate.first_seen_sample,
                   "last_sample": candidate.last, "observed_samples": candidate.observed_samples,
                   "low": candidate.low, "high": candidate.high, "peak_width_m": candidate.peak_width_m}
        else:
            row = {"source": "narrow", "epoch": self.epoch, "first_sample": candidate['start'],
                   "last_sample": candidate['last'], "observed_samples": candidate['samples'],
                   "low": candidate['low'], "high": candidate['high'], "peak_width_m": candidate.get('peak_width_m', 0)}
            if 'competing_group_id' in candidate:
                row['competing_group_id'] = candidate['competing_group_id']
        since = candidate.observation_wait_since if isinstance(candidate, Contact) else candidate.get('observation_wait_since')
        closed = candidate.observation_closed_sample if isinstance(candidate, Contact) else candidate.get('observation_closed_sample')
        if closed is not None:
            row.update(observation_wait_since=since, observation_closed_sample=closed)
        row.update(outcome=outcome, reason=reason, closed_sample=closed_sample)
        if owner_id is not None:
            row['owner_id'] = owner_id
        return row

    def _record_candidate(self, candidate, outcome, reason, closed_sample=None, owner_id=None):
        row = self._candidate_row(candidate, outcome, reason, closed_sample, owner_id)
        self._candidate_decisions.append(row)
        if reason == 'observation_budget':
            self.event_audit.append({'action': 'candidate_observation_closed', 'sample': self.last_sample, **deepcopy(row)})

    def _unresolve_candidate(self, c, reason):
        if not c.confirmed and c.candidate_outcome == 'pending':
            self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
            c.candidate_outcome = 'unresolved'
            self._record_candidate(c, 'unresolved', reason)

    def _exclude_nonstep(self, start, end, epoch, clear_before):
        # The declared non-step observation never represented support. Correct
        # only its own occupancy interval; do not fill neighbouring unknowns.
        phases = []
        for a, b, count, ep in self.phases:
            points = sorted({a, b, *[x for x in (start, end) if a < x < b]})
            for left, right in zip(points, points[1:]):
                value = count - int(ep == epoch and start <= left < end and count > 0)
                if phases and phases[-1][1:] == [left, value, ep]:
                    phases[-1][1] = right
                else:
                    phases.append([left, right, value, ep])
        self.phases = phases
        if self.last_occupied == end - 1:
            occupied = [c.last for c in self.contacts if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}
                        and c.interrupted != 'masked_contact_boundary']
            occupied += [q['last'] for q in self._narrow_candidates if q['start'] != start]
            self.last_occupied = max(occupied, default=None)
        if (clear_before is not None and epoch == self.epoch
                and not any(x['sample'] >= clear_before for x in self.issues)):
            self._clear_since = max(clear_before, (self.last_occupied + 1) if self.last_occupied is not None else clear_before)

    def _suspend_exit(self):
        if self._exit_evidence and self._suspended_exit is None:
            self._suspended_exit = (self._exit_contact_id, self._exit_blocked_through_id, self._clear_since)
        self._exit_evidence = False

    def _commit_contacts(self):
        self._close_observation_waits()
        self._sync_touch_publications()
        ordered = sorted(self.contacts, key=lambda c: (c.start, c.id))
        for c in ordered:
            if c.id in self._committed_contacts:
                continue
            if any(q['start'] < c.start and q.get('observation_closed_sample') is None for q in self._narrow_candidates):
                break
            if (self._pending_group_before(c)
                    or (self._contact_competition_waiting(c) and c in self.active and not self._publication_closed)
                    or (not self._publication_closed and not c.confirmed and c.end is None
                        and c in self.active and c.candidate_outcome != 'associated_fragment'
                        and c.observation_closed_sample is None
                        and not any(g['state'] == 'closed_unknown' and any(
                            x['source_id'] == c.ownership_source_id for x in g['sources'])
                            for g in self._ownership_groups))):
                break
            self._committed_contacts.add(c.id)
            self._commit_cursor = len(self._committed_contacts)
            event = self._touch_events.get(c.id)
            if event is None or not event['active']:
                if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}:
                    self._identity_known = False
                continue
            prior = next((x for x in reversed(ordered)
                                if x.epoch == c.epoch and x.label
                                and (x.start, x.id) < (c.start, c.id)), None)
            closed_onsets = [x.start for x in ordered if x.epoch == c.epoch
                and (x.observation_closed_sample is not None or any(
                    r['outcome'] == 'unresolved' and r['reason'] == 'observation_budget'
                    for r in x.ownership_competition))]
            closed_onsets += [q['start'] for q in self._narrow_candidates if q.get('observation_closed_sample') is not None]
            closed_onsets += [d['first_sample'] for d in self._candidate_decisions if d['epoch'] == c.epoch
                and d['source'] == 'narrow' and d.get('observation_closed_sample') is not None]
            closed_onsets += [s['first_sample'] if s['first_sample'] is not None else g['unresolved_since_sample']
                for g in self._ownership_groups if g['epoch'] == c.epoch and g['close_reason'] == 'observation_budget'
                for s in g['sources'] if s['source_id'] not in assigned_sources(g)
                and not self._touch_events.get(s.get('contact_id'), {}).get('active')]
            gap = prior is not None and any(prior.start < onset <= c.start for onset in closed_onsets)
            if gap:
                self._identity_known = False
            prior_label = prior.label if prior is not None and not gap else 'B'
            self._last_label = 'A' if prior_label == 'B' else 'B'
            c.label = self._last_label
            self.event_audit.append({'action': 'sequence_commit', 'sample': self.last_sample,
                'event_id': event['event_id'], 'touch_sample': event['touch_sample'], 'label': c.label})
            side = {"Left": "left", "Right": "right"}.get(self.config.starting_foot, "unknown")
            if not self._identity_known:
                side = 'unknown'
            elif c.label == 'B' and side != 'unknown':
                side = 'right' if side == 'left' else 'left'
            c.side = side
            prior = [x for x in [x for x in ordered if (x.start, x.id) < (c.start, c.id)]
                     if x.confirmed and x.label and x.epoch == c.epoch and not x.problem
                     and not any(x.start < onset <= c.start for onset in closed_onsets)]
            if any(x.label == c.label and x.last >= c.start for x in prior):
                c.problem, c.side = 'identity_uncertain', 'unknown'
                self._identity_known = False
        self._review_direction()
        if self._suspended_exit is not None and not self._narrow_candidates:
            owner, blocked, clear = self._suspended_exit
            sequence = sorted((c for c in self.contacts if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}), key=lambda c: (c.start, c.id))
            if (sequence and sequence[-1].id == owner and not sequence[-1].problem
                    and not sequence[-1].interrupted and all(c.candidate_outcome == 'excluded_nonstep'
                                                            for c in self.contacts[owner + 1:])):
                self._exit_evidence, self._exit_contact_id = True, owner
                self._exit_blocked_through_id = blocked
                if clear is not None:
                    self._clear_since = clear
                self._suspended_exit = None

            elif any(c.id > owner and (c.confirmed or c.problem or c.interrupted) for c in self.contacts):
                self._suspended_exit = None

    def _close_observation_waits(self):
        grouped = {s['source_id'] for g in self._ownership_groups for s in g['sources']}
        for c in self.active:
            if (c.confirmed or c.candidate_outcome != 'pending' or c.ownership_source_id in grouped
                    or c.observation_wait_since is None
                    or self.last_sample-c.observation_wait_since < self.OWNERSHIP_OBSERVATION_BUDGET_MS):
                continue
            c.observation_closed_sample = self.last_sample
            c.candidate_outcome = 'unresolved'
            self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
            self._record_candidate(c, 'unresolved', 'observation_budget', self.last_sample)
        for q in self._narrow_candidates:
            if (q.get('observation_closed_sample') is None and q.get('observation_wait_since') is not None
                    and self.last_sample-q['observation_wait_since'] >= self.OWNERSHIP_OBSERVATION_BUDGET_MS):
                q['observation_closed_sample'] = self.last_sample
                self._mark_unknown_start(q['start'])
                self._record_candidate(q, 'unresolved', 'observation_budget', self.last_sample)
                self._narrow_barriers.append((q['start'], q['start']+1, self.epoch))
                self._identity_known = False

    def _review_direction(self):
        points = []
        for c in sorted(self.contacts, key=lambda c: (c.start, c.id)):
            if not c.label or not self._touch_events.get(c.id, {}).get('active'):
                continue
            point = self._direction_positions.get(c.id)
            if c.problem == 'unresolved_fragment_join' and point is None and c.end is not None:
                edges, evidence = running_position_history(self, c)
                if evidence['valid']:
                    values = sorted(((self.positions[lo]+self.positions[hi])/2, b-a)
                                    for a,b,lo,hi in edges)
                    weight = sum(w for _,w in values); cumulative = 0
                    for value,w in values:
                        cumulative += w
                        if cumulative >= weight/2:
                            break
                    point = {'value_m': value, 'window': [c.start,c.end],
                             'evidence_available_sample': evidence['evidence_available_sample'],
                             'group_id': evidence['group_id'], 'source_ids': evidence['source_ids']}
                    self._direction_positions[c.id] = point
            elif not c.problem and not c.interrupted and c.edges:
                a,b,lo,hi = c.edges[-1]
                if not any(lo-1 <= i <= hi+1 for i in self.device.bad_indices):
                    point = {'value_m': (self.positions[lo]+self.positions[hi])/2,
                             'window': [a,b], 'evidence_available_sample': self.last_sample}
            if point is not None:
                points.append((c,point))
        for (a,ap),(b,bp) in zip(points,points[1:]):
            pair = (a.id,b.id)
            if (a.epoch != b.epoch or pair in self._direction_pairs
                    or self._direction_last_touch is not None and b.start <= self._direction_last_touch):
                continue
            delta = bp['value_m']-ap['value_m']
            if abs(delta) < self.DIRECTION_DISPLACEMENT_M:
                continue
            self._direction_pairs.add(pair)
            self._direction_last_touch = b.start
            evidence = {'sample': self.last_sample, 'contact_ids': list(pair),
                        'original_touch_samples': [a.start,b.start], 'delta_m': delta,
                        'positions': [deepcopy(ap),deepcopy(bp)],
                        'rule_version': 'certified_direction_independent_geometry_v1'}
            if self.direction and delta*self.direction < 0:
                self.finished_reason = 'turn_detected'
                if not b.problem:
                    b.problem = 'turn_detected'
                self.event_audit.append({'action': 'direction_turn', **evidence})
            elif not self.direction:
                self.direction = 1 if delta > 0 else -1
                self.event_audit.append({'action': 'direction_established', 'direction': self.direction, **evidence})

    def _defer_narrow_candidates(self, groups, n, masked_groups=()):
        # Known optical owners can retain an isolated new island pending local
        # evidence. This gate never imposes a minimum width for a running foot.
        def matches(low, high, candidates):
            return [c for c in candidates
                    if low <= c['high'] and high >= c['low']]
        pending = []
        for p in self._narrow_candidates:
            visible = any(matches(low, high, [p]) for low, high in groups)
            if not visible:
                p['isolated_clear'] &= self._local_clear(self._current_frame, p['low'], p['high'])
            if n - p['last'] < self.config.release_ms or (visible and n - p['last'] <= self.config.release_ms):
                pending.append(p)
            else:
                excluded = p['samples'] == 1 and p['low'] == p['high'] and p['isolated_clear'] and not p.get('clear_gaps')
                self._record_candidate(p, 'excluded_nonstep' if excluded else 'unresolved',
                                       'closed_isolated_single_sample' if excluded else 'short_narrow_contact', n)
                if excluded:
                    self._exclude_nonstep(p['start'], p['last'] + 1, self.epoch, p.get('clear_before_candidate'))
                else:
                    self._mark_unknown_start(p['start'])
                    self._narrow_unknown.append((p['start'], p['last'] + 1, self.epoch))
                    if p.get('observation_closed_sample') is None:
                        self._narrow_barriers.append((p['start'], p['last'] + 1, self.epoch))
                    self._identity_known = False
                    self._suspended_exit = None
        owners = [self._owners(low, high, groups) for low, high in groups]
        anchored = any(len(cs) == 1 and cs[0].confirmed and not cs[0].problem
                       and not cs[0].interrupted for cs in owners)
        immature_owner = any(len(cs) == 1 and not cs[0].interrupted
                             and cs[0].problem in {None, 'simultaneous_contacts', 'unresolved_coalescence'} for cs in owners)
        # A later wide contact cannot overtake an earlier pending touch in the
        # contact sequence. Promote the earlier candidates with their own times.
        force = any(not cs and (any(self.positions[low] <= self.positions[h] and self.positions[high] >= self.positions[l]
                                   for l, h in masked_groups)
                                or self.positions[high] - self.positions[low] >= self.NARROW_CANDIDATE_WIDTH_M
                                or self.positions[low] == self.positions[0]
                                or self.positions[high] == self.positions[-1])
                    for (low, high), cs in zip(groups, owners))
        kept, seeds, consumed, ambiguous = [], {}, set(), False
        for (low, high), cs in zip(groups, owners):
            ps = matches(low, high, pending)
            if len(ps) > 1:
                ambiguous = True
                kept.append((low, high))
                continue
            p = ps[0] if ps else None
            if cs:
                kept.append((low, high))
                if p is not None:
                    if len(cs) != 1 or not cs[0].confirmed:
                        ambiguous = True
                        continue
                    self._narrow_unknown.append((p['start'], p['last'] + 1, self.epoch))
                    self._record_candidate(p, 'unresolved' if p.get('observation_closed_sample') is not None else 'associated_fragment',
                                           'joined_existing_footprint', n, cs[0].id if len(cs) == 1 else None)
                    consumed.add(id(p))
                    self._suspended_exit = None
                continue
            boundary = self.positions[low] == self.positions[0] or self.positions[high] == self.positions[-1]
            width = self.positions[high] - self.positions[low]
            competing_group = next((g['id'] for g in self._ownership_groups
                if ownership_record(g) and g['tracking_ended_sample'] is None and g['epoch'] == self.epoch
                and any(self.positions[low] <= self.positions[h] + self.MATCH_MARGIN_M
                        and self.positions[high] >= self.positions[l] - self.MATCH_MARGIN_M
                        for l, h in g['islands'])), None)
            if (p is None and (not force or competing_group is not None)
                    and not boundary and width < self.NARROW_CANDIDATE_WIDTH_M
                    and (anchored or (immature_owner and low == high
                                      and self._local_clear(self._previous_frame, low, high))
                         or competing_group is not None)):
                p = {'start': n, 'last': n - 1, 'low': low, 'high': high,
                     'samples': 0, 'edges': [], 'touch_known': not self._recovering,
                     'isolated_clear': (not self._recovering and self._previous_frame is not None
                                        and self._previous_frame.sample_index == n - 1
                                        and self._local_clear(self._previous_frame, low, high)),
                     'clear_before_candidate': self._clear_since, 'clear_gaps': [], 'peak_width_m': width,
                     'observation_wait_since': n}
                pending.append(p)
                if competing_group is not None:
                    p['competing_group_id'] = competing_group
                self._suspend_exit()
                self._exit_blocked_through_id = len(self.contacts) - 1
            if p is None:
                kept.append((low, high))
                continue
            p['peak_width_m'] = max(p.get('peak_width_m', 0), width)
            if p['samples'] and n > p['last'] + 1:
                p['clear_gaps'].append((p['last'] + 1, n))
            # A nearby narrow island can still be part of the recovered sole.
            # Persistence alone does not resolve that competing attribution.
            if (p.get('observation_closed_sample') is None and (boundary or width >= self.NARROW_CANDIDATE_WIDTH_M
                    or ('competing_group_id' not in p and (force or (not anchored and not immature_owner)
                        or n - p['start'] + 1 >= max(self.config.min_contact_time, self.config.confirmation_ms))))):
                kept.append((low, high))
                seeds[(low, high)] = p
                consumed.add(id(p))
            else:
                p.update(last=n, low=low, high=high, samples=p['samples'] + 1)
                self._observe_source(p.setdefault('valid_sample_intervals', []), n)
                if p['edges'] and p['edges'][-1][1:] == [n, low, high]:
                    p['edges'][-1][1] = n + 1
                else:
                    p['edges'].append([n, n + 1, low, high])
        self._narrow_candidates = [p for p in pending if id(p) not in consumed]
        return kept, seeds, ambiguous

    def _coalesce_immature_islands(self, groups, n, affected):
        # A briefly coalescing optical group retains evidence but cannot establish
        # a foot identity or per-foot event/position. Mature fusion stays ambiguous.
        unavailable = {c.id for region in self._local_regions for c in region['members']}
        for low, high in groups:
            if (self.positions[high] - self.positions[low] > self.MAX_CLUSTER_WIDTH_M
                    or any(self.positions[low] <= self.positions[h] and self.positions[high] >= self.positions[l]
                           for l, h in affected)):
                continue
            cs = [c for c in self.active if c.id not in unavailable and low <= c.high and high >= c.low]
            ps = [q for q in self._narrow_candidates if low <= q['high'] and high >= q['low']]
            if len(cs) + len(ps) != 2:
                continue
            evidence = []
            for c in cs:
                if (c.confirmed or c.problem or c.interrupted or not c.touch_known
                        or c.last != n - 1 or c.epoch != self.epoch):
                    break
                evidence.append((c.start, c.last, c.peak_width_m, c.observed_samples, c.edges, c))
            else:
                for q in ps:
                    if not q['touch_known'] or q.get('clear_gaps') or q['last'] != n - 1:
                        break
                    evidence.append((q['start'], q['last'], q.get('peak_width_m', 0), q['samples'], q['edges'], q))
                else:
                    if len(evidence) == 2:
                        evidence.sort(key=lambda r: r[0])
                        first, second = evidence
                        immature = (n - first[0] <= self.config.confirmation_ms
                                    and all(r[2] < self.NARROW_CANDIDATE_WIDTH_M for r in evidence))
                        # A source may grow beyond the narrow gate before the
                        # second island joins. Retain only this early, local
                        # growth as an unknown group; it is never foot evidence.
                        left = self.positions[low] - self.MATCH_MARGIN_M
                        right = self.positions[high] + self.MATCH_MARGIN_M
                        widths = [(self.positions[r[4][0][3]] - self.positions[r[4][0][2]],
                                   self.positions[r[4][-1][3]] - self.positions[r[4][-1][2]])
                                  for r in evidence if r[4]]
                        other = [g for g in groups if g != (low, high)]
                        growth = (len(widths) == 2
                                  and n - second[0] <= self.config.confirmation_ms
                                  and n - first[0] < max(self.config.min_contact_time, self.config.confirmation_ms)
                                  and all(r[2] < 2 * self.CLUSTER_GAP_M for r in evidence)
                                  and all(w[1] >= r[2] - 1e-9 for w, r in zip(widths, evidence))
                                  and any(r[2] > w[0] + 1e-9 for w, r in zip(widths, evidence))
                                  and all(not c.has_unknown for c in cs)
                                  and self.positions[0] <= left and right <= self.positions[-1]
                                  and not any(left <= self.positions[i] <= right for i in self.device.bad_indices)
                                  and (not other or len(other) == 1 and any(
                                      c.confirmed and c.touch_known and not c.problem and not c.interrupted
                                      and c not in cs
                                      and self.positions[other[0][0]] <= self.positions[c.high] + self.MATCH_MARGIN_M
                                      and self.positions[other[0][1]] >= self.positions[c.low] - self.MATCH_MARGIN_M
                                      for c in self.active)))
                        if (0 < second[0] - first[0] <= self.config.confirmation_ms
                                and (immature or growth)):
                            parent = first[5] if isinstance(first[5], Contact) else None
                            # Preserve the two original islands before modifying their owner.
                            source_rows = [self._candidate_row(r[5], 'associated_fragment', 'immature_islands_coalesced', n)
                                           for r in evidence]
                            if parent is None:
                                parent = Contact(len(self.contacts), self.epoch, '', 'unknown', first[0], first[1],
                                                 low, high, False, observed_samples=first[3], edges=list(first[4]),
                                                 first_seen_sample=first[0],
                                                 valid_sample_intervals=[list(x) for x in first[5].get('valid_sample_intervals', [])],
                                                 ownership_source_id=first[5].get('ownership_source_id'))
                                self.contacts.append(parent)
                                self.active.append(parent)
                            for row, r in zip(source_rows, evidence):
                                row.pop('contact_id', None)
                                row.update(source='immature_island', source_id=f"{self.epoch}:{r[0]}:{row['low']}:{row['high']}",
                                           owner_id=parent.id)
                                self._candidate_decisions.append(row)
                            for c in cs:
                                if c is not parent:
                                    c.candidate_outcome, c.problem = 'associated_fragment', 'associated_fragment'
                                    self.active.remove(c)
                            self._narrow_candidates = [q for q in self._narrow_candidates if all(q is not r[5] for r in evidence)]
                            parent.problem, parent.touch_known, parent.side = 'unresolved_coalescence', False, 'unknown'
                            parent.candidate_outcome = 'unresolved_group'
                            parent.peak_width_m = self.positions[high] - self.positions[low]
                            self._identity_known = False
                            self._suspended_exit = None
                            self._exit_evidence = False
                            self._mark_unknown_start(first[0])


    @staticmethod
    def _union_sample_intervals(intervals):
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(end, merged[-1][1])
            else:
                merged.append([start, end])
        return merged

    @staticmethod
    def _observe_source(intervals, sample):
        if intervals and sample <= intervals[-1][1]:
            intervals[-1][1] = max(intervals[-1][1], sample + 1)
        else:
            intervals.append([sample, sample + 1])

    def _ownership_source(self, candidate):
        if isinstance(candidate, Contact):
            if candidate.ownership_source_id is None:
                candidate.ownership_source_id = self._next_ownership_source
                self._next_ownership_source += 1
            source_id = candidate.ownership_source_id
            intervals = candidate.valid_sample_intervals
            since = candidate.ownership_unresolved_since
        else:
            if 'ownership_source_id' not in candidate:
                candidate['ownership_source_id'] = self._next_ownership_source
                self._next_ownership_source += 1
            source_id = candidate['ownership_source_id']
            intervals = candidate.get('valid_sample_intervals', [])
            since = candidate.get('ownership_unresolved_since')
        closed = candidate.observation_closed_sample if isinstance(candidate, Contact) else candidate.get('observation_closed_sample')
        wait_since = candidate.observation_wait_since if isinstance(candidate, Contact) else candidate.get('observation_wait_since')
        if isinstance(candidate, Contact) and self._contact_competition_pending(candidate):
            wait_since = min(r['detected_sample'] for r in candidate.ownership_competition
                             if r['outcome'] in {'pending','unresolved'})
        inherit_wait = (closed is not None or isinstance(candidate, Contact) and self._contact_competition_pending(candidate)
                        or not isinstance(candidate, Contact) and 'competing_group_id' in candidate)
        return {**self._candidate_row(candidate, 'group_pending', 'ownership_pending'),
                'source_id': source_id, 'unresolved_since_sample': since,
                **({'observation_wait_since': wait_since} if inherit_wait else {}),
                'evidence_at_join': asdict(candidate) if isinstance(candidate, Contact) else deepcopy(candidate),
                'valid_sample_intervals': [list(x) for x in intervals]}

    def _close_ownership_groups(self, reason, sample):
        for group in self._ownership_groups:
            if group['tracking_ended_sample'] is not None:
                continue
            if group['state'] == 'observing':
                group.update(state='closed_unknown', closed_sample=sample, close_reason=reason)
            group['tracking_ended_sample'] = sample
            group['tracking_end_reason'] = reason
            for source in group['sources']:
                source.update(outcome='unresolved', closed_sample=max(source['joined_sample'], group['closed_sample']),
                              reason=group['close_reason'])

    def _observe_ownership_groups(self, groups, frame, observation=None):
        """Keep connected-source evidence without assigning it to either foot.

        Source intervals precede the join; subsequent shared samples belong to
        the group once only. Closed-budget groups keep following occupancy.
        """
        n = frame.sample_index
        observe_review_frame(self, groups, frame, observation)
        live = [g for g in self._ownership_groups if g['tracking_ended_sample'] is None]
        previous = {g['id']: list(g['islands']) for g in live}
        coverage = {}
        candidates = [*self.active, *self._narrow_candidates]
        for low, high in groups:
            touched = [g for g in live if g['tracking_ended_sample'] is None
                       and any(low <= right and high >= left for left, right in previous[g['id']])]
            sources = [c for c in candidates if low <= (c.high if isinstance(c, Contact) else c['high'])
                       and high >= (c.low if isinstance(c, Contact) else c['low'])]
            if not touched and len(sources) < 2:
                continue
            rows = [self._ownership_source(c) for c in sources]
            if touched:
                group = min(touched, key=lambda g: (g['unresolved_since_sample'], g['id']))
                for other in touched:
                    if other is group:
                        continue
                    group['sources'].extend(deepcopy(s) for s in other['sources']
                                            if s['source_id'] not in {x['source_id'] for x in group['sources']})
                    group['merged_group_ids'].append(other['id'])
                    group.setdefault('source_decisions', []).extend(deepcopy(other.get('source_decisions', [])))
                    other_owner = ownership_record(other)
                    if other_owner:
                        group.setdefault('competing_owner_ids', []).append(other_owner['owner_id'])
                    group['valid_sample_intervals'] = self._union_sample_intervals(
                        group['valid_sample_intervals'] + other['valid_sample_intervals'])
                    coverage.setdefault(group['id'], []).extend(coverage.pop(other['id'], []))
                    previous[group['id']].extend(previous[other['id']])
                    # A budget that already expired cannot be reopened by merging.
                    if other['state'] == 'closed_unknown' and group['state'] == 'observing':
                        group.update(state=other['state'], closed_sample=other['closed_sample'],
                                     close_reason=other['close_reason'])
                    other.update(state='merged', merged_into=group['id'], tracking_ended_sample=n,
                                 tracking_end_reason='sources_connected')
            else:
                since = min([n, *[s['unresolved_since_sample'] for s in rows
                                  if s['unresolved_since_sample'] is not None]])
                group = {'id': len(self._ownership_groups), 'epoch': self.epoch, 'sources': [],
                         'unresolved_since_sample': since, 'last_sample': n,
                         'state': 'observing', 'closed_sample': None, 'close_reason': None,
                         'tracking_ended_sample': None, 'tracking_end_reason': None,
                         'occupancy_end_sample': None, 'clear_since_sample': None,
                         'islands': [[low, high]], 'valid_sample_intervals': [], 'observed_samples': 0,
                         'observation_runs': [], 'merged_group_ids': []}
                self._ownership_groups.append(group)
                live.append(group)
                previous[group['id']] = [[low, high]]
            for source in rows:
                if source['source_id'] not in {s['source_id'] for s in group['sources']}:
                    source['joined_sample'] = n
                    first = source['first_sample']
                    source['review_observations'] = (deepcopy([r for r in self._source_review_frames
                        if first <= r[0] < n]) if first is not None and n-first <= SHORT_ISLAND_MS else [])
                    group['sources'].append(source)
                    group['valid_sample_intervals'] = self._union_sample_intervals(
                        group['valid_sample_intervals'] + source['valid_sample_intervals'])
                    if source['unresolved_since_sample'] is not None:
                        group['unresolved_since_sample'] = min(group['unresolved_since_sample'],
                                                               source['unresolved_since_sample'])
            coverage.setdefault(group['id'], []).append([low, high])
        for group in live:
            if group['tracking_ended_sample'] is not None:
                continue
            islands = coverage.get(group['id'], [])
            if islands:
                group['islands'] = sorted(set(map(tuple, islands)))
                group['last_sample'] = n
                group['clear_since_sample'] = None
                reliable = all(all(frame.valid_bits[low:high + 1])
                               and not any(low - 1 <= i <= high + 1 for i in self.device.bad_indices)
                               and (observation is None or observation.reliable(low, high))
                               for low, high in islands)
                if reliable:
                    self._observe_source(group['valid_sample_intervals'], n)
                shape = [list(x) for x in group['islands']]
                runs = group['observation_runs']
                if runs and runs[-1][1] == n and runs[-1][2:] == [shape, reliable]:
                    runs[-1][1] = n + 1
                else:
                    runs.append([n, n + 1, shape, reliable])
            else:
                reliable_clear = all(all(frame.valid_bits[low:high + 1])
                                     and not any(frame.contact_bits[low:high + 1])
                                     and (observation is None or observation.release_reliable(low, high, .035))
                                     for low, high in group['islands'])
                if reliable_clear:
                    if group['clear_since_sample'] is None:
                        group['clear_since_sample'] = n
                    if n - group['clear_since_sample'] + 1 >= self.config.release_ms:
                        group['occupancy_end_sample'] = group['clear_since_sample']
                        group['tracking_ended_sample'] = n
                        group['tracking_end_reason'] = 'reliable_clear'
                        if group['state'] == 'observing':
                            group.update(state='closed_unknown', closed_sample=n, close_reason='reliable_clear')
                else:
                    group['clear_since_sample'] = None
            group['observed_samples'] = sum(end - start for start, end in group['valid_sample_intervals'])
            budget_start = min([group['unresolved_since_sample'],
                *[s['observation_wait_since'] for s in group['sources'] if s.get('observation_wait_since') is not None]])
            if budget_start < group['unresolved_since_sample']:
                group['observation_wait_since'] = budget_start
            if (group['state'] == 'observing'
                    and n - budget_start >= self.OWNERSHIP_OBSERVATION_BUDGET_MS):
                group.update(state='closed_unknown', closed_sample=n, close_reason='observation_budget')
            if group['state'] == 'closed_unknown':
                for source in group['sources']:
                    source.update(outcome='unresolved', closed_sample=max(source['joined_sample'], group['closed_sample']),
                                  reason=group['close_reason'])

    def _groups(self, bits):
        if b'\x01' not in bits:
            return []
        groups = []
        # Sort by actual geometry, including reversed segments and custom wire order.
        for i in sorted(blocked_indices(bits), key=self.positions.__getitem__):
            previous = groups[-1][-1] if groups else None
            pitch = max(self.device.layout.segments[i // 96].pitch_m,
                        self.device.layout.segments[previous // 96].pitch_m) if previous is not None else 0
            if (previous is not None and i == previous + 1
                    and self.positions[i] - self.positions[previous] <= 1.5 * pitch):
                groups[-1].append(i)
            else:
                groups.append([i])
        return [(g[0], g[-1]) for g in groups]

    def _masked_islands(self, groups):
        # Known bad beams hide coverage, never prove a physical foot identity.
        # Joining only these separators preserves a censored optical envelope.
        joined = []
        for low, high in groups:
            previous = joined[-1][1] if joined else None
            if (previous is not None and low > previous + 1
                    and all(i in self.device.bad_indices for i in range(previous + 1, low))
                    and all(self.positions[i + 1] - self.positions[i] <= 1.5 * max(
                        self.device.layout.segments[i // 96].pitch_m,
                        self.device.layout.segments[(i + 1) // 96].pitch_m)
                            for i in range(previous, low))):
                joined[-1] = (joined[-1][0], high)
            else:
                joined.append((low, high))
        return joined

    def _associate_inner_fragments(self, groups):
        # A known footprint may separate into heel/toe islands. Associate only
        # islands supported by one existing envelope, never two tracked feet.
        # An inner island anchors association while a rolling edge may move
        # within the same margin already used for ordinary contact matching.
        owners, anchored = {}, set()
        self._split_ambiguous = set()
        held_ids = {c.id for region in self._local_regions for c in region['members']}
        for index, (low, high) in enumerate(groups):
            lo, hi = self.positions[low], self.positions[high]
            candidates = [c for c in self.active
                          if c.id not in held_ids and low <= c.high and high >= c.low]
            private = [q for q in self._narrow_candidates if low <= q['high'] and high >= q['low']]
            if len(candidates) == 1 and not private:
                c = candidates[0]
                owners.setdefault(c.id, []).append(index)
                if self.positions[c.low] <= lo and hi <= self.positions[c.high]:
                    anchored.add(c.id)
        merged, consumed = [], set()
        for owner, indices in owners.items():
            if len(indices) > 1:
                if (owner not in anchored or self.positions[groups[indices[-1]][1]]
                        - self.positions[groups[indices[0]][0]] > self.MAX_CLUSTER_WIDTH_M):
                    self._split_ambiguous.add(owner)
                merged.append((groups[indices[0]][0], groups[indices[-1]][1]))
                consumed.update(indices)
        return sorted(merged + [g for i, g in enumerate(groups) if i not in consumed],
                      key=lambda g: self.positions[g[0]])

    def _owners(self, low, high, groups, observation=None):
        unavailable = {c.id for region in self._local_regions for c in region['members']}
        actual = [c for c in self.active if c.id not in unavailable and low <= c.high and high >= c.low]
        if actual:
            return actual
        # A nearby disjoint island is never absorbed while the old footprint
        # remains visible. Only a short clear/unknown boundary permits censored
        # occupancy continuation, never a reliable new geometry or touch.
        candidates = [c for c in self.active
                      if c.id not in unavailable and not any(l <= c.high and h >= c.low for l, h in groups)
                      and (c.release_start is not None
                           or observation is not None and observation.neighbour_unknown(c.low, c.high, self.MATCH_MARGIN_M))
                      and self.last_sample - c.last <= (self.config.release_ms + 10 if observation is not None else self.config.release_ms)
                      and self.positions[low] <= self.positions[c.high] + self.MATCH_MARGIN_M
                      and self.positions[high] >= self.positions[c.low] - self.MATCH_MARGIN_M]
        return candidates

    def _local_unknown(self, start, end):
        if self._narrow_unknown and self._narrow_unknown[-1][1] == start and self._narrow_unknown[-1][2] == self.epoch:
            a, _, e = self._narrow_unknown[-1]
            self._narrow_unknown[-1] = (a, end, e)
        else:
            self._narrow_unknown.append((start, end, self.epoch))

    def _hold_local_regions(self, groups, n):
        """Keep optical occupancy separate from unobservable per-source shape.

        A connected projection of two tracked sources cannot reveal either
        source's boundary. Keep their IDs and earlier touches, never vote the
        union into a foot, and follow its current coverage until actual clear.
        """
        held, consumed, regions = set(), set(), []
        for region in self._local_regions:
            group_id = region.get('ownership_group_id')
            while group_id is not None and self._ownership_groups[group_id]['state'] == 'merged':
                group_id = self._ownership_groups[group_id]['merged_into']
            region['ownership_group_id'] = group_id
            indices = [i for i, (low, high) in enumerate(groups)
                       if low <= region['high'] and high >= region['low']]
            members = region['members']
            # Separated mature envelopes can resume their own observations,
            # but their intervening position/lift remains censored permanently.
            separated = (not region['private'] and len(indices) == len(members) > 1
                         and all(sum(low <= c.high and high >= c.low for c in members) == 1
                                 for i in indices for low, high in [groups[i]])
                         and all(sum(groups[i][0] <= c.high and groups[i][1] >= c.low
                                     for i in indices) == 1 for c in members))
            if separated:
                continue
            if indices:
                region['low'] = min(groups[i][0] for i in indices)
                region['high'] = max(groups[i][1] for i in indices)
                region['last'] = n
                consumed.update(indices)
                self._local_unknown(n, n + 1)
                for c in members:
                    c.last, c.absent_samples, c.release_start = n, 0, None
                    held.add(c.id)
            if n - region['last'] < self.config.release_ms:
                regions.append(region)
            else:
                for c in members:
                    c.end, c.lift_known = region['last'] + 1, False
                    if c in self.active:
                        self.active.remove(c)
        self._local_regions = regions
        for index, (low, high) in enumerate(groups):
            if index in consumed:
                continue
            unavailable = held | {c.id for region in self._local_regions for c in region['members']}
            members = [c for c in self.active if c.id not in unavailable and low <= c.high and high >= c.low]
            private = [q for q in self._narrow_candidates if low <= q['high'] and high >= q['low']]
            unsupported_split = any(c.id in self._split_ambiguous for c in members)
            shape_jump = (len(members) == 1 and members[0].confirmed
                          and abs(self.positions[low] + self.positions[high]
                                  - self.positions[members[0].low] - self.positions[members[0].high]) / 2 > .18)
            oversized = self.positions[high] - self.positions[low] > self.MAX_CLUSTER_WIDTH_M
            if len(members) + len(private) < 2 and not shape_jump and not unsupported_split and not oversized:
                continue
            # Bounded early sources already handled by the immature optical
            # provenance gate remain unknown groups rather than foot claims.
            self._preserved_stops = self._stop_intervals()
            self.issues.append({'code': 'ambiguous_contacts', 'scope': 'local_projection_overlap',
                                'sample': n, 'frame_index': self._current_frame.frame_index})
            self._identity_known = False
            self._exit_evidence = False
            self._exit_contact_id = None
            self._suspended_exit = None
            self._local_unknown(n, n + 1)
            if not members and not private:
                self._mark_unknown_start(n)
            for c in members:
                c.problem = c.problem or 'unresolved_fragment_join'
                c.first_uncertain_sample = c.first_uncertain_sample if c.first_uncertain_sample is not None else n
                c.touch_known &= c.confirmed
                c.side, c.has_unknown = 'unknown', True
                c.last, c.absent_samples, c.release_start = n, 0, None
                if not c.confirmed:
                    c.candidate_outcome = 'unresolved_group'
                    self._mark_unknown_start(c.start)
                held.add(c.id)
            for q in private:
                self._local_unknown(q['start'], n + 1)
                self._record_candidate(q, 'unresolved', 'unresolved_fragment_join', n,
                                       members[0].id if len(members) == 1 else None)
                self._narrow_candidates.remove(q)
            member_ids = {c.id for c in members}
            coverage = {index}
            for i, (left, right) in enumerate(groups):
                owners = {c.id for c in self.active if c.id not in unavailable
                          and left <= c.high and right >= c.low}
                if owners and owners <= member_ids:
                    coverage.add(i)
            self._local_regions.append({'low': min(groups[i][0] for i in coverage),
                                        'high': max(groups[i][1] for i in coverage), 'last': n,
                                        'ownership_group_id': next((g['id'] for g in self._ownership_groups
                                            if g['tracking_ended_sample'] is None and any(
                                                low <= right and high >= left for left, right in g['islands'])), None),
                                        'members': members, 'private': bool(private) or shape_jump or unsupported_split})
            consumed.update(coverage)
        return [g for i, g in enumerate(groups) if i not in consumed], held, bool(consumed)

    def process(self, frame, observation=None, *, masked_contact=False):
        if self.finished_reason:
            return
        if observation is not None:
            frame = observation.measurement_frame()
        if frame.stream_id != self.device.stream_id or frame.layout != self.device.layout:
            self.break_continuity("device_changed", frame.frame_index)
            self.finished_reason = "device_changed"
            return
        n = frame.sample_index
        if n <= self.last_sample:
            self.break_continuity("counter_reset", frame.frame_index)
            self.finished_reason = "counter_reset"
            return
        if n != self.last_sample + 1 or frame.dropped_frames_before:
            self.break_continuity("frame_gap", frame.frame_index)
        self.last_sample, self.last_time = n, frame.sample_time_s
        self._current_frame = frame
        if (len(frame.contact_bits) != len(self.positions) or len(frame.valid_bits) != len(self.positions)
                or (observation is None and not all(frame.valid_bits))
                or any(x != "frame_gap" for x in frame.quality_flags)):
            self.break_continuity("invalid_sample", frame.frame_index)
            return
        raw_groups = self._groups(frame.contact_bits)
        affected = [(low, high) for low, high in raw_groups if any(
            0 <= j < len(self.positions) and frame.contact_bits[j]
            and abs(self.positions[j] - self.positions[i]) <= .04
            and self.positions[low] <= self.positions[j] <= self.positions[high]
            for i in self.device.bad_indices for j in (i - 1, i + 1))] if masked_contact else []
        if masked_contact:
            self._duration_censored = True
            self._mark_unknown_start(n)
            self._duration_clear_upper = None
            if not affected:
                if not self._masked_contact_uncertain or self.active or self._narrow_candidates:
                    self.break_continuity("masked_contact_boundary", frame.frame_index)
                self._masked_contact_uncertain = True
                return
            if not self._masked_contact_uncertain:
                self.issues.append({"code": "masked_contact_boundary", "sample": n,
                                    "frame_index": frame.frame_index})
            self._identity_known = False
            self._exit_evidence = False
            self._exit_contact_id = None
            self._suspended_exit = None
        self._masked_contact_uncertain = masked_contact
        if (self._duration_censored and self._duration_clear_upper is None
                and b'\x01' not in frame.contact_bits and b'\x00' not in frame.valid_bits
                and (observation is None or not observation.unresolved_segments)):
            self._duration_clear_upper = n
        if observation is not None:
            if observation.unresolved_segments:
                self._duration_censored = True
                self._duration_clear_upper = None
            for c in list(self.active):
                if observation.affected(c.low, c.high):
                    self._preserved_stops = self._stop_intervals()
                    self._unresolve_candidate(c, 'local_unknown_timeout')
                    c.interrupted = 'local_unknown_timeout'
                    self.active.remove(c)
                    self._identity_known = False
            for c in list(self.active):
                if (c.interrupted != 'local_unknown_timeout' and ((not c.confirmed and c.has_unknown
                     and n - c.start >= max(self.config.min_contact_time, self.config.confirmation_ms) + 10)
                        or (c.candidate_since is not None
                            and n - c.candidate_since >= self.config.release_ms + 10))):
                    self._preserved_stops = self._stop_intervals()
                    self._unresolve_candidate(c, 'local_unknown_timeout')
                    c.interrupted = 'local_unknown_timeout'
                    self._identity_known = False
        if not masked_contact and raw_groups:
            self.last_occupied = n
        groups = self._masked_islands(raw_groups) if masked_contact else raw_groups
        self._observe_ownership_groups(raw_groups, frame, observation)
        groups = self._associate_inner_fragments(groups)
        self._coalesce_immature_islands(groups, n, affected)
        groups, locally_held, local_unknown = self._hold_local_regions(groups, n)
        occupancy = len(groups) + int(local_unknown)
        seeds, pending_ambiguous = {}, False
        if observation is None:
            groups, seeds, pending_ambiguous = self._defer_narrow_candidates(groups, n, affected)
        matches, used = [], set()
        ambiguous = pending_ambiguous
        for low, high in groups:
            lo, hi = self.positions[low], self.positions[high]
            candidates = [c for c in self._owners(low, high, groups, observation) if c.id not in locally_held]
            ambiguous |= len(candidates) > 1 or hi - lo > self.MAX_CLUSTER_WIDTH_M
            c = candidates[0] if len(candidates) == 1 else None
            if c:
                ambiguous |= c.id in used
                used.add(c.id)
            matches.append((low, high, c))
        if ambiguous:
            self._mark_unknown_start(n)
            for q in seeds.values():
                self._mark_unknown_start(q['start'])
                self._record_candidate(q, 'unresolved', 'ambiguous_contacts')
            if not self._ambiguous:
                self.break_continuity("ambiguous_contacts", frame.frame_index)
            self._ambiguous = True
            self._phase(n, -1)
            return
        self._ambiguous = False
        multiple_islands = len(raw_groups) > 2 and sum(c is None for _, _, c in matches) > 1
        if len(raw_groups) > 2 and any(c is None for _, _, c in matches) and not self._multiple_islands_now:
            self.issues.append({'code': 'ambiguous_contacts', 'scope': 'local_multiple_islands',
                                'sample': n, 'frame_index': frame.frame_index})
        self._multiple_islands_now = multiple_islands
        low_edge, high_edge = self.positions[0], self.positions[-1]
        observed = set(locally_held)
        new = []
        matches.sort(key=lambda x: seeds.get((x[0], x[1]), {}).get('start', n))
        for low, high, c in matches:
            if c is not None and observation is not None and not (low <= c.high and high >= c.low):
                c.problem = c.problem or 'unresolved_fragment_join'
                c.first_uncertain_sample = c.first_uncertain_sample if c.first_uncertain_sample is not None else n
                c.touch_known &= c.confirmed
                c.side, c.has_unknown = 'unknown', True
                self._identity_known = False
                self._local_unknown(c.last + 1, n + 1)
            if c is None:
                boundary = self.positions[low] == low_edge or self.positions[high] == high_edge
                c = Contact(len(self.contacts), self.epoch, "", "unknown", n, n, low, high,
                            not self._recovering and not boundary)
                c.first_seen_sample = n
                c.observation_wait_since = n
                c.clear_before_candidate = self._clear_since
                c.isolated_clear = (observation is None and not self._recovering and self._previous_frame is not None
                                    and self._previous_frame.sample_index == n - 1
                                    and self._local_clear(self._previous_frame, low, high))
                seed = seeds.get((low, high))
                if seed is not None:
                    c.start, c.touch_known = seed['start'], seed['touch_known']
                    c.first_seen_sample = seed['start']
                    c.observed_samples, c.edges = seed['samples'], list(seed['edges'])
                    c.valid_sample_intervals = [list(x) for x in seed.get('valid_sample_intervals', [])]
                    c.ownership_source_id = seed.get('ownership_source_id')
                    c.ownership_unresolved_since = seed.get('ownership_unresolved_since')
                    c.observation_wait_since = seed.get('observation_wait_since', n)
                    c.observation_closed_sample = seed.get('observation_closed_sample')
                    if 'competing_group_id' in seed:
                        self._ownership_source(c)
                        c.ownership_competition.append({'group_id': seed['competing_group_id'],
                            'source_id': c.ownership_source_id, 'detected_sample': seed['observation_wait_since'],
                            'evidence_start_sample': c.start, 'outcome': 'pending',
                            'rule_version': 'existing_narrow_competition_gate_v1',
                            'reason': 'promoted_narrow_candidate_competition'})
                    c.peak_width_m = seed.get('peak_width_m', 0)
                    c.isolated_clear = seed.get('isolated_clear', False)
                    c.clear_before_candidate = seed.get('clear_before_candidate')
                    if seed.get('clear_gaps'):
                        c.problem = 'uncertain_short_clear'
                        c.first_uncertain_sample = seed['clear_gaps'][0][0]
                        self._identity_known = False
                if observation is not None:
                    edge = observation.edge(low, high, 1)
                    if edge:
                        c.start = edge.sample
                        c.edge_estimates['touch'] = [edge.left_sample, edge.right_sample]
                        neighbours = [x for x in self.active
                                      if observation.neighbour_unknown(x.low, x.high, self.MATCH_MARGIN_M)
                                      and self.positions[low] <= self.positions[x.high] + self.MATCH_MARGIN_M
                                      and self.positions[high] >= self.positions[x.low] - self.MATCH_MARGIN_M]
                        if neighbours:
                            self._preserved_stops = self._stop_intervals()
                        for x in [*neighbours, c] if neighbours else []:
                            x.problem = x.problem or 'unresolved_fragment_join'
                            x.first_uncertain_sample = (x.first_uncertain_sample if x.first_uncertain_sample is not None
                                                        else edge.left_sample)
                            x.touch_known &= x.confirmed
                            x.side, x.has_unknown = 'unknown', True
                            self._identity_known = False
                        if neighbours:
                            self._local_unknown(edge.left_sample, n + 1)
                        if c.start < n:
                            self._phase_adjustments.append((c.start, n, 1, c.epoch))
                    if observation.affected(low, high, observation.recovery_segments):
                        c.touch_known = False
                        neighbours = [x for x in self.active
                                      if self.positions[low] <= self.positions[x.high] + self.MATCH_MARGIN_M
                                      and self.positions[high] >= self.positions[x.low] - self.MATCH_MARGIN_M]
                        if neighbours:
                            self._preserved_stops = self._stop_intervals()
                        for x in [*neighbours, c] if neighbours else []:
                            x.problem = x.problem or 'unresolved_fragment_join'
                            x.first_uncertain_sample = (x.first_uncertain_sample if x.first_uncertain_sample is not None else n)
                            x.touch_known &= x.confirmed
                            x.side, x.has_unknown = 'unknown', True
                            self._identity_known = False
                        if neighbours:
                            self._local_unknown(n, n + 1)
                if multiple_islands:
                    self._identity_known = False
                if not c.touch_known or c.problem:
                    self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
                self._suspend_exit()
                self.contacts.append(c)
                self.active.append(c)
                new.append(c)
            if any(self.positions[low] <= self.positions[h] and self.positions[high] >= self.positions[l]
                   for l, h in affected):
                if c.first_masked_sample is None:
                    c.first_masked_sample = n
                    self._unresolve_candidate(c, 'masked_contact_boundary')
                    self._preserved_stops = self._stop_intervals()
                if c in new:
                    c.touch_known = False
                c.interrupted = 'masked_contact_boundary'
                c.side = 'unknown'
            observed.add(c.id)
            if c.last < n - 1 and c.release_start is not None:
                # A sub-confirmation clear interval cannot silently count as continuous support.
                self._preserved_stops = self._stop_intervals()
                c.problem = c.problem or "uncertain_short_clear"
                self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
                if c.first_uncertain_sample is None:
                    c.first_uncertain_sample = c.last + 1
                self._identity_known = False
                for contact in self.contacts[c.id:]:
                    contact.side = "unknown"
            c.source_islands = tuple((l, h) for l, h in raw_groups if low <= l and h <= high)
            c.last, c.low, c.high = n, low, high
            c.peak_width_m = max(c.peak_width_m, self.positions[high] - self.positions[low])
            reliable = observation is None or observation.reliable(low, high)
            c.observed_samples += int(reliable and not c.interrupted)
            if reliable and not c.interrupted:
                self._observe_source(c.valid_sample_intervals, n)
            if reliable:
                c.last_reliable_sample = n
            if reliable:
                c.absent_samples = 0
                c.release_start = None
                c.candidate_since = None
                if c.edges and c.edges[-1][1] == n and c.edges[-1][2:] == [low, high]:
                    c.edges[-1][1] = n + 1
                else:
                    c.edges.append([n, n + 1, low, high])
            if observation is not None:
                c.has_unknown |= observation.affected(low, high, observation.unknown_segments) or bool(observation.edge(low, high, 1))
            if (not c.interrupted and c.observation_closed_sample is None
                    and n - c.start + 1 >= max(self.config.confirmation_ms, self.config.min_contact_time)
                    and c.observed_samples >= self.config.confirmation_ms):
                if not c.confirmed:
                    c.confirmed = True
                    c.confirmed_sample = n
                    c.candidate_outcome = 'unresolved_group' if c.problem in {'unresolved_coalescence', 'unresolved_multiple_islands'} else 'confirmed_contact'
                    if self.origin is None and c.touch_known and not c.problem:
                        self.origin = c.start / 1000
                        upper = c.edge_estimates.get('touch', [c.start, c.start])[1]
                        if (c.touch_known and self._duration_start_unknown_from is not None
                                and upper < self._duration_start_unknown_from):
                            self._duration_start_censored = False
            endpoint = high_edge if self.direction > 0 else low_edge
            at_exit = self.direction and (self.positions[high] == endpoint or self.positions[low] == endpoint)
            if reliable:
                c.endpoint_run = c.endpoint_run + 1 if at_exit else 0
            if (reliable and c.confirmed and not c.problem and not c.interrupted
                    and c.id > self._exit_blocked_through_id
                    and c.endpoint_run >= self.config.confirmation_ms):
                self._exit_evidence = True
                self._exit_contact_id = c.id
        # Rolling within the same tracked contact does not revoke its confirmed
        # terminal-beam evidence. Earlier support may overlap, but a later
        # contact cannot inherit or reestablish the older contact's proof.
        if (new or (self._exit_contact_id is not None
                    and self._exit_contact_id != next((c.id for c in reversed(self.contacts)
                                                      if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}), None))
                or any(c.id == self._exit_contact_id and (c.problem or c.interrupted)
                       for c in self.active)):
            self._exit_evidence = False
        if len(new) > 1:
            self._identity_known = False
            for c in new:
                c.ownership_unresolved_since = n
                self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
                c.side, c.problem = "unknown", "simultaneous_contacts"
        for c in list(self.active):
            if c.id not in observed:
                if not c.confirmed:
                    c.isolated_clear &= observation is None and self._local_clear(frame, c.low, c.high)
                if c.interrupted == 'local_unknown_timeout':
                    if observation.reliable(c.low, c.high):
                        self.active.remove(c)
                    continue
                c.endpoint_run = 0
                reliable = observation is None or observation.release_reliable(c.low, c.high, self.MATCH_MARGIN_M)
                edge = observation.edge(c.low, c.high, 0) if observation is not None else None
                if (observation is not None and observation.neighbour_unknown(
                        c.low, c.high, self.MATCH_MARGIN_M)):
                    edge = None
                if observation is not None and c.candidate_since is None:
                    c.candidate_since = n
                if c.release_start is None and (reliable or edge):
                    c.release_start = c.last + 1
                    if observation is not None and not edge and n > c.candidate_since:
                        left = c.last_reliable_sample
                        if left is None or n - left > 11:
                            self._preserved_stops = self._stop_intervals()
                            c.release_start = None
                            self._unresolve_candidate(c, 'local_unknown_timeout')
                            c.interrupted = 'local_unknown_timeout'
                            self.active.remove(c)
                            self._identity_known = False
                            continue
                        c.release_start = (left + n) / 2
                        c.edge_estimates['lift'] = [left, n]
                    if not edge and c.release_start < n:
                        self._phase_adjustments.append((c.release_start, n, -1, c.epoch))
                if edge:
                    c.release_start = edge.sample
                    c.edge_estimates['lift'] = [edge.left_sample, edge.right_sample]
                    if edge.sample < n:
                        self._phase_adjustments.append((edge.sample, n, -1, c.epoch))
                if reliable:
                    c.absent_samples += 1
                if c.absent_samples >= self.config.release_ms:
                    c.end = c.release_start if c.interrupted != 'masked_contact_boundary' else None
                    c.lift_known = not c.interrupted and self.positions[c.low] != low_edge and self.positions[c.high] != high_edge
                    if not c.confirmed:
                        excluded = (c.observed_samples == 1 and c.low == c.high and c.isolated_clear
                                    and not c.problem and not c.interrupted and not c.has_unknown)
                        previous_outcome = c.candidate_outcome
                        c.candidate_outcome = 'excluded_nonstep' if excluded else 'unresolved'
                        c.problem = c.problem or c.interrupted or ('excluded_nonstep' if excluded else 'short_contact')
                        if previous_outcome != 'unresolved':
                            self._record_candidate(c, c.candidate_outcome, c.problem, n)
                        if excluded:
                            self._exclude_nonstep(c.start, c.last + 1, c.epoch, c.clear_before_candidate)
                        else:
                            self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
                            self._identity_known = False
                            for later in self.contacts[c.id + 1:]:
                                later.side = 'unknown'
                    self.active.remove(c)
        self._recover_ownership_groups()
        self._commit_contacts()
        self._recovering = False
        held = sum(c.id not in observed and c.release_start is None
                   and c.candidate_since is not None and not c.interrupted for c in self.active)
        self._phase(n, -1 if local_unknown or masked_contact or any(c.id in observed and c.problem in {'unresolved_coalescence', 'unresolved_multiple_islands', 'unresolved_fragment_join'} for c in self.active)
                    or (observation is not None and observation.unresolved_segments) else occupancy + held)
        if occupancy:
            if not masked_contact:
                self.last_occupied = n
            self._clear_since = None
        elif observation is not None and observation.unresolved_segments:
            self._clear_since = None
        elif self.origin is not None:
            if self._clear_since is None:
                self._clear_since = n
            if (self.config.has_auto_stop and self._exit_evidence
                    and n - self._clear_since + 1 >= self.config.exit_clear_ms):
                self.finished_reason = "passage_complete"
        self._previous_frame = frame
        if self.origin is not None and n - self._last_visual >= 40:
            self._last_visual = n
            self.timeline.append({"timestamp_s": n / 1000 - self.origin,
                                  "segment_ids": tuple(s.segment_id for s in self.device.layout.segments),
                                  "contact_bits": list(frame.contact_bits), "positions_m": self.positions,
                                  "valid_bits": list(frame.valid_bits), "quality_flags": list(frame.quality_flags),
                                  "feet": [{"contact_id": c.id, "side": c.side, "label": c.label,
                                            "centroid_cm": (self.positions[c.low] + self.positions[c.high]) * 50,
                                            "length_cm": (self.positions[c.high] - self.positions[c.low]) * 100,
                                            "status": "confirmed" if c.confirmed and not c.problem and not c.interrupted else "candidate"}
                                           for c in self.active]})

    def _phase(self, n, count):
        if self.phases and self.phases[-1][1:] == [n, count, self.epoch]:
            self.phases[-1][1] = n + 1
        else:
            self.phases.append([n, n + 1, count, self.epoch])

    def _toe(self, c):
        if self._contact_competition_pending(c):
            return metric(reason='unresolved_contact_competition')
        if not self.direction:
            return metric(reason="direction_unknown")
        edges, evidence = c.edges, None
        if c.confirmed and c.problem == 'unresolved_fragment_join' and not c.interrupted:
            edges, evidence = running_position_history(self, c)
        if (c.problem or c.interrupted or not c.confirmed) and not (evidence and evidence['valid']):
            result = metric(reason=c.problem or c.interrupted or "short_contact")
            if evidence is not None:
                result['evidence'] = evidence
            return result
        edge = 3 if self.direction > 0 else 2
        boundary = self.positions[-1] if self.direction > 0 else self.positions[0]
        if any(self.positions[r[edge]] == boundary for r in edges):
            return metric(reason="toe_clipped")
        # Weighted sliding platforms; adjacent pitch is read from the physical segment.
        candidates = []
        for i, row in enumerate(edges):
            values, duration = [], 0
            for r in edges[i:]:
                if values and r[0] != previous_end:
                    break
                pos = self.positions[r[edge]]
                pitch = self.device.layout.segments[r[edge] // 96].pitch_m
                if values and max(max(v for v, _ in values), pos) - min(min(v for v, _ in values), pos) > pitch + 1e-9:
                    break
                values.append((pos, r[1] - r[0]))
                previous_end = r[1]
                duration += r[1] - r[0]
                if duration >= self.config.toe_platform_ms:
                    ordered = sorted(values)
                    def kth(k):
                        total = 0
                        for v, weight in ordered:
                            total += weight
                            if total > k:
                                return v
                    candidates.append((kth((duration - 1) // 2) + kth(duration // 2)) / 2)
                    break
        if not candidates:
            return metric(reason="no_stable_toe_platform")
        result = metric(max(candidates) if self.direction > 0 else min(candidates))
        if evidence is not None:
            result['evidence'] = evidence
        return result

    def _support(self, start, end, epoch):
        releases = [group_release_evidence(self._ownership_groups, c.id) for c in self.contacts]
        releases = [{**r, 'end_sample': r['occupied_until_sample']} for r in releases if r is not None and r['occupancy_valid']
                    and next(g for g in self._ownership_groups if g['id'] == r['group_id'])['epoch'] == epoch]
        known_groups = {r['group_id'] for r in releases}
        known_owners = {ownership_record(g)['owner_id'] for g in self._ownership_groups if g['id'] in known_groups}
        known_sources = {s['source_id'] for g in self._ownership_groups if g['id'] in known_groups for s in g['sources']}
        def covered(a, b):
            cursor = max(start, a)
            for r in sorted(releases, key=lambda r: r['start_sample']):
                if r['start_sample'] <= cursor < r['end_sample']:
                    cursor = max(cursor, r['end_sample'])
            return cursor >= min(end, b)
        # Temporal coverage alone cannot absorb a remote unknown occupant.
        independent_unknown = [(p['start'], p['last'] + 1, self.epoch) for p in self._narrow_candidates]
        independent_unknown += [(c.start, c.end if c.end is not None else c.last + 1, c.epoch)
                                for c in self.contacts if (not c.confirmed or self._contact_competition_pending(c))
                                and c.candidate_outcome not in {'associated_fragment','excluded_nonstep'}]
        independent_unknown += [(min(n for n in (c.first_uncertain_sample, c.first_masked_sample,
                                    c.last_reliable_sample + 1 if c.last_reliable_sample is not None else c.start)
                                    if n is not None), c.end if c.end is not None else c.last + 1, c.epoch)
                                for c in self.contacts if c.confirmed and (c.problem or c.interrupted)
                                and c.id not in known_owners and releases
                                and c.candidate_outcome not in {'associated_fragment','excluded_nonstep'}]
        independent_unknown += [(g['valid_sample_intervals'][0][0], g['last_sample'] + 1, g['epoch'])
                                for g in self._ownership_groups if g['state'] != 'merged'
                                and g['id'] not in known_groups and g['valid_sample_intervals']]
        independent_unknown += [(d['first_sample'], d['last_sample'] + 1, d['epoch'])
                                for d in self._candidate_decisions if d['source'] == 'narrow'
                                and d['outcome'] == 'unresolved'
                                and not any(s['source_id'] in known_sources and s['first_sample'] == d['first_sample']
                                            and s['low'] == d['low'] for g in self._ownership_groups for s in g['sources'])]
        if (any(e == epoch and a < end and b > start for a,b,e in independent_unknown)
                or any(e == epoch and a < end and b > start and not covered(a,b) for a,b,e in self._narrow_unknown)):
            return None, "unconfirmed_narrow_fragment"
        totals = {0: 0, 1: 0, 2: 0}
        cursor = start
        for a, b, count, e in self.phases:
            if b <= start or a >= end:
                continue
            lo, hi = max(start, a), min(end, b)
            if lo != cursor or e != epoch:
                return None, "incomplete_observation"
            if count < 0 or any(r['start_sample'] < hi and r['end_sample'] > lo for r in releases):
                if not covered(lo,hi):
                    return None, "incomplete_observation"
                occupants = [(r['start_sample'], r['end_sample']) for r in releases]
                recovered_ids = {ownership_record(g)['owner_id'] for g in self._ownership_groups if ownership_record(g)}
                occupants += [(c.start, min(c.end if c.end is not None else c.last + 1,
                                    *[n for n in (c.first_uncertain_sample, c.first_masked_sample,
                                        c.last_reliable_sample + 1 if c.last_reliable_sample is not None else None)
                                      if n is not None]))
                              for c in self.contacts if c.epoch == epoch and c.id not in recovered_ids
                              and c.candidate_outcome not in {'associated_fragment','excluded_nonstep'}
                              and c.confirmed]
                boundaries = sorted({lo,hi,*[x for a,b in occupants for x in (a,b) if lo < x < hi]})
                for left,right in zip(boundaries,boundaries[1:]):
                    occupied = sum(a <= left < b for a,b in occupants)
                    if not 1 <= occupied <= 2:
                        return None, "incomplete_observation"
                    totals[occupied] += right-left
                cursor = hi
                continue
            if count == 0 and b - a < self.config.release_ms:
                return None, "uncertain_short_clear"
            boundaries = sorted({lo, hi, *[x for left, right, _, ep in self._phase_adjustments
                                          if ep == epoch for x in (left, right) if lo < x < hi]})
            for left, right in zip(boundaries, boundaries[1:]):
                midpoint = (left + right) / 2
                inferred = count + sum(delta for a, b, delta, ep in self._phase_adjustments
                                       if ep == epoch and a <= midpoint < b)
                if not 0 <= inferred <= 2:
                    return None, 'incomplete_observation'
                totals[inferred] += right - left
            cursor = hi
        if cursor != end:
            return None, "incomplete_observation"
        return {k: v / 1000 for k, v in totals.items()}, None

    def _flight_release_reason(self, start, end, epoch, rows):
        # The last foot to leave can precede both contacts bounding this step.
        # Validate every transition into clear space, not just the adjacent foot.
        for a, b, count, e in self.phases:
            if count != 0 or e != epoch or b <= start or a >= end:
                continue
            lo, hi = max(start, a), min(end, b)
            boundaries = sorted({lo, hi, *[x for left, right, _, ep in self._phase_adjustments
                                          if ep == epoch for x in (left, right) if lo < x < hi]})
            if not any(sum(delta for left, right, delta, ep in self._phase_adjustments
                           if ep == epoch and left <= (u + v) / 2 < right) == 0
                       for u, v in zip(boundaries, boundaries[1:])):
                continue
            departures = [c for c in self.contacts if c.epoch == epoch and c.end is not None
                          and (c.end == a or any(left == c.end and right == a and delta == -1 and ep == epoch
                                                for left, right, delta, ep in self._phase_adjustments))]
            if not departures or any(not rows[c.id]["lift_s"]["valid"] for c in departures):
                return "lift_not_observed"
        return None

    def _temporal_problem(self, c, through_sample):
        # A later dropout cannot invalidate an already confirmed earlier event.
        if (c.problem in {"uncertain_short_clear", "unresolved_fragment_join"} and c.first_uncertain_sample is not None
                and through_sample < c.first_uncertain_sample
                and c.first_uncertain_sample - c.start >= max(self.config.confirmation_ms, self.config.min_contact_time)):
            return None
        return c.problem

    def _stop_intervals(self):
        stops = dict(self._preserved_stops)
        for c in self.contacts:
            end = c.end if c.end is not None else c.last + 1
            if c.end is None and c.last_reliable_sample is not None:
                end = c.last_reliable_sample + 1
            if not c.problem and not c.interrupted and end - c.start >= self.config.stop_threshold_s * 1000:
                stops[c.start] = max(stops.get(c.start, end), end)
        return sorted(stops.items())

    def summary(self):
        origin = self.origin or 0
        stops = self._stop_intervals()
        def barrier(cs, temporal=False):
            uncertain = self._ownership_barriers() + self._narrow_barriers + [(p['start'], p['start']+1 if p.get('observation_closed_sample') is not None else p['last'] + 1, self.epoch)
                                                for p in self._narrow_candidates]
            if any(e == cs[0].epoch and a < cs[-1].start and b > cs[0].start
                   for a, b, e in uncertain):
                return "unconfirmed_narrow_fragment"
            for c in cs:
                published = self._touch_events.get(c.id)
                known_touch = published is not None and published['active']
                problem = self._temporal_problem(c, cs[-1].start) if temporal else c.problem
                grouped = any(s['source_id'] == c.ownership_source_id
                              for g in self._ownership_groups for s in g['sources'])
                if temporal and known_touch and grouped and problem == 'unresolved_fragment_join':
                    problem = None
                if (not temporal and problem == 'unresolved_fragment_join'
                        and rows[c.id]['toe_m'].get('evidence', {}).get('valid')):
                    problem = None
                if problem or not c.confirmed:
                    return problem or c.interrupted or "short_contact"
                if (not temporal and c.first_masked_sample is not None and c.first_masked_sample <= cs[-1].start):
                    return "masked_contact_boundary"
            if len({c.epoch for c in cs}) != 1:
                return "continuity_break"
            if any(cs[0].start < b and cs[-1].start >= a for a, b in stops):
                return "stop_interval"
            return None
        rows = []
        for c in self.contacts:
            problem = c.problem or (None if c.confirmed else c.interrupted or "short_contact")
            if self._contact_competition_pending(c):
                problem = 'unresolved_contact_competition'
            touch = metric(c.start / 1000 - origin if c.touch_known else None,
                           self._temporal_problem(c, c.start) or (None if c.confirmed else c.interrupted or "short_contact")
                           or (None if c.touch_known else "touch_not_observed"))
            published = self._touch_events.get(c.id)
            if published is not None and published['active']:
                touch = metric(published['touch_sample'] / 1000 - origin)
            elif self._contact_competition_pending(c):
                touch = metric(reason='unresolved_contact_competition')
            lift = metric(c.end / 1000 - origin if c.end is not None and c.lift_known else None,
                          problem or c.interrupted or (None if c.lift_known else "lift_not_observed"))
            release = group_release_evidence(self._ownership_groups, c.id)
            if release is not None:
                lift = metric(release['end_sample'] / 1000 - origin if release['missing_reason'] is None else None,
                              release['missing_reason'])
            reason = (release['missing_reason'] if release is not None else problem or c.interrupted) or (
                "incomplete_contact" if not (touch["valid"] and lift["valid"]) else None)
            if any(c.start < b and (c.end or c.last + 1) > a for a, b in stops):
                reason = "stop_interval"
            rows.append({"id": c.id, "epoch": c.epoch, "label": c.label, "side": c.side,
                         "identity_source": "manual_first_foot_and_alternation" if c.side != "unknown" else "alternation_only",
                         "touch_s": touch, "lift_s": lift, "toe_m": self._toe(c),
                         "contact_s": metric((c.end - c.start) / 1000 if c.end is not None else None, reason),
                         "candidate_outcome": c.candidate_outcome,
                         "first_seen_sample": c.first_seen_sample,
                         "touch_sample": c.start if touch['valid'] and 'touch' not in c.edge_estimates else None,
                         "lift_sample": c.end if lift['valid'] and 'lift' not in c.edge_estimates else None,
                         "confirmed_sample": c.confirmed_sample,
                         "metric_evidence": {"lift": release or {"basis": "observed_contact_boundary"}}})
            if c.ownership_competition and c.candidate_outcome != 'associated_fragment':
                rows[-1]['ownership_competition'] = deepcopy(c.ownership_competition)
        steps, cycles = [], []
        sequence = sorted((c for c in self.contacts if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}), key=lambda c: (c.start, c.id))
        for i in range(1, len(sequence)):
            a, b = sequence[i - 1:i + 1]
            ar, br = rows[a.id], rows[b.id]
            reason = barrier([a, b])
            time_barrier = barrier([a, b], temporal=True)
            temporal = time_barrier or (None if ar["touch_s"]["valid"] and br["touch_s"]["valid"] else "touch_not_observed")
            temporal = temporal or ("pending_touch_order" if not a.label or not b.label else None)
            dt = metric((b.start - a.start) / 1000, temporal)
            spatial = reason or (None if ar["toe_m"]["valid"] and br["toe_m"]["valid"] else "toe_unavailable")
            length = metric(abs(br["toe_m"]["value"] - ar["toe_m"]["value"]) if not spatial else None, spatial)
            speed = metric(length["value"] / dt["value"] if length["valid"] and dt["valid"] and dt["value"] > 0 else None,
                           reason or (None if length["valid"] and dt["valid"] and dt["value"] > 0 else "length_or_time_unavailable"))
            support, phase_reason = self._support(a.start, b.start, a.epoch)
            flight_reason = temporal or phase_reason
            if support and support[0] > 0:
                # Positive flight depends on release -> next touch, not on the
                # preceding stance's (possibly clipped) touch event.
                flight_reason = (time_barrier or phase_reason
                                 or (None if br["touch_s"]["valid"] else "touch_not_observed")
                                 or self._flight_release_reason(a.start, b.start, a.epoch, rows))
            flight = metric(support[0] if support else None, flight_reason)
            steps.append({"from_id": a.id, "to_id": b.id, "side": b.side,
                          "length_m": length, "time_s": dt, "speed_m_s": speed, "flight_s": flight})
            if i < 2:
                continue
            x, y, z = sequence[i - 2:i + 1]
            xr, zr = rows[x.id], rows[z.id]
            why = barrier([x, y, z], temporal=True)
            if not all(c.label for c in (x,y,z)) or x.label != z.label or x.label == y.label:
                why = why or "identity_uncertain"
            time_reason = why or (None if xr["touch_s"]["valid"] and zr["touch_s"]["valid"] else "touch_not_observed")
            support, phase_reason = self._support(x.start, z.start, x.epoch)
            phase_reason = time_reason or phase_reason
            if any(c.last + 1 <= z.start and not rows[c.id]['lift_s']['valid'] for c in (x, y)):
                phase_reason = phase_reason or "lift_not_observed"
            spatial_reason = barrier([x, y, z]) or why or (None if xr["toe_m"]["valid"] and zr["toe_m"]["valid"] else "toe_unavailable")
            cycles.append({"from_id": x.id, "to_id": z.id, "label": x.label, "side": x.side,
                           "duration_s": metric((z.start - x.start) / 1000, time_reason),
                           "length_m": metric(abs(zr["toe_m"]["value"] - xr["toe_m"]["value"]) if not spatial_reason else None, spatial_reason),
                           "contact_s": metric(xr["contact_s"]["value"], xr["contact_s"]["missing_reason"]),
                           "swing_s": metric((z.start - x.end) / 1000 if x.end is not None else None,
                                             time_reason or (None if xr["lift_s"]["valid"] else "lift_not_observed")),
                           **{name: metric(support[count] if support else None,
                                          phase_reason or (self._flight_release_reason(x.start, z.start, x.epoch, rows)
                                                           if count == 0 else None))
                              for name, count in (("flight_s", 0), ("single_support_s", 1), ("double_support_s", 2))}})
        def values(records, key):
            return [r[key]["value"] for r in records if r[key]["valid"]]
        def stats(records, keys):
            result = {}
            for key in keys:
                v = values(records, key)
                result[key] = {"count": len(v), "mean": sum(v) / len(v) if v else None}
            return result
        flight_cycles = [c for c in cycles if c["flight_s"]["valid"] and c["flight_s"]["value"] > 0]
        grouped = {"all": stats(cycles, ("duration_s", "length_m", "contact_s", "swing_s", "single_support_s", "double_support_s", "flight_s")),
                   "with_flight": stats(flight_cycles, ("duration_s", "length_m", "contact_s", "swing_s", "single_support_s", "double_support_s", "flight_s"))}
        sides = {}
        for key, records in (("step_length_m", steps), ("contact_s", rows)):
            field = "length_m" if key == "step_length_m" else key
            left, right = (values([r for r in records if r["side"] == side], field) for side in ("left", "right"))
            lm, rm = (sum(v) / len(v) if v else None for v in (left, right))
            eligible = len(left) >= 3 and len(right) >= 3 and lm + rm > 0
            sides[key] = {"left_count": len(left), "right_count": len(right), "left_mean": lm, "right_mean": rm,
                          "asymmetry_percent": metric(abs(lm - rm) / ((lm + rm) / 2) * 100 if eligible else None,
                                                       None if eligible else "insufficient_bilateral_samples")}
        lengths = values(steps, "length_m")
        timed = [s for s in steps if s["speed_m_s"]["valid"]]
        speed = sum(s["length_m"]["value"] for s in timed) / sum(s["time_s"]["value"] for s in timed) if timed else None
        end = self.last_occupied + 1 if self.last_occupied is not None else None
        if (self.last_occupied is not None and any(c.end is not None and 'lift' in c.edge_estimates
                                                 and c.end >= self.last_occupied for c in self.contacts)):
            end = max(c.end for c in self.contacts if c.end is not None and c.end >= self.last_occupied)
        duration = max(0, end / 1000 - origin) if self.origin is not None and end is not None else None
        if (self._duration_start_censored or
                (self._duration_censored and (self._duration_clear_upper is None
                                             or end is None or end < self._duration_clear_upper))):
            duration = None
        return {"segment_count": len(self.device.layout.segments), "nominal_length_m": len(self.device.layout.segments),
                "direction": self.direction, "duration_s": duration, "valid_steps": sum(s["time_s"]["valid"] for s in steps),
                "valid_cycles": sum(c["duration_s"]["valid"] for c in cycles), "step_lengths_m": lengths,
                "running_speed_m_s": speed, "contacts": rows, "steps": steps, "cycles": cycles,
                "event_publications": self.touch_events, "event_audit": deepcopy(self.event_audit),
                "ownership_recoveries": [deepcopy(g["recovery"]) for g in self._ownership_groups if g.get("recovery")],
                "record_count": len(rows), "confirmed_contacts": sum(c.confirmed for c in self.contacts),
                "valid_touches": self.reliable_touch_count,
                "metric_policy": METRIC_POLICY,
                "valid_contact_durations": sum(r['contact_s']['valid'] for r in rows),
                "valid_step_lengths": sum(r['length_m']['valid'] for r in steps),
                "valid_step_speeds": len(timed),
                "valid_stride_lengths": sum(r['length_m']['valid'] for r in cycles),
                "valid_support_cycles": sum(all(r[k]['valid'] for k in ('flight_s', 'single_support_s', 'double_support_s')) for r in cycles),
                "candidate_decisions": list(self._candidate_decisions)
                    + [self._candidate_row(q, 'unresolved' if q.get('observation_closed_sample') is not None else 'pending',
                        'observation_budget' if q.get('observation_closed_sample') is not None else 'awaiting_release_or_confirmation',
                        q.get('observation_closed_sample')) for q in self._narrow_candidates]
                    + [self._candidate_row(c, 'pending', 'awaiting_release_or_confirmation') for c in self.active
                       if not c.confirmed and c.candidate_outcome == 'pending'],
                "groups": grouped, "sides": sides,
                "step_statistics": stats(steps, ("length_m", "time_s", "speed_m_s", "flight_s")),
                "flight_cycle_count": len(flight_cycles),
                "zero_flight_cycle_count": sum(c["flight_s"]["valid"] and c["flight_s"]["value"] == 0 for c in cycles),
                "unknown_flight_cycle_count": sum(not c["flight_s"]["valid"] for c in cycles),
                "stops": [{"start_s": a / 1000 - origin, "end_s": b / 1000 - origin} for a, b in stops],
                "issues": [{**x, "time_s": x["sample"] / 1000 - origin} for x in self.issues],
                "status": "出口证据不足，可手动结束" if self._clear_since is not None and not self._exit_evidence else "跑步中"}

    def build_report(self, reason, export_frames=(), export_timestamps=()):
        self._close_ownership_groups(reason, self.last_sample)
        self._publication_closed = True
        self._commit_contacts()
        summary = self.summary()
        return OvergroundRunningReport(
            touch_count=summary['valid_touches'],
            lift_count=sum(r['lift_s']['valid'] for r in summary['contacts']),
            finish_reason=reason, running_summary=summary, visual_timeline=tuple(self.timeline),
            export_frames=export_frames, export_timestamps=export_timestamps,
            report_config_snapshot={**self.config.to_dict(), "device": self.device.snapshot(),
                                    "algorithm": "overground_running_v1.12", "metric_policy": METRIC_POLICY, "spatial_reference": "toe_to_toe",
                                    "toe_method": "furthest_stable_leading_edge_platform_median",
                                    "readiness_stale_ms": 500, "data_timeout_ms": 1000,
                                    "tracking": {"direction_displacement_m": self.DIRECTION_DISPLACEMENT_M,
                                                 "cluster_gap_m": self.CLUSTER_GAP_M,
                                                 "match_margin_m": self.MATCH_MARGIN_M,
                                                 "max_cluster_width_m": self.MAX_CLUSTER_WIDTH_M,
                                                 "narrow_candidate_width_m": self.NARROW_CANDIDATE_WIDTH_M,
                                                 "narrow_candidate_scope": "local_candidate_evidence_before_identity",
                                                 "fragment_association": "unique_actual_previous_coverage_and_shape_history"},
                                    "real_world_validation": "pending"})
