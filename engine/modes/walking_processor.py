"""Single-pass overground walking on calibrated beam coordinates.

Beam interruption is an optical contact proxy, not force-plate contact. Ambiguous
merges and acquisition gaps break continuity. Bounded local unknowns carry evidence.
"""
from dataclasses import asdict, dataclass, field
from copy import deepcopy
from collections import deque

from engine.ground_source_review import (SHORT_ISLAND_MS, ownership_record, assigned_sources,
    observe_review_frame, review_group_sources)
from statistics import median

from engine.ground_metric_evidence import group_release_evidence, metric
from engine.ground_position_evidence import record_centre_sample, walking_centre_position
from config.test_report import GaitTestReport
from config.walking_config import WalkingConfig
from hardware.sensor_frame import blocked_indices
from hardware.walking_preflight import PreparedDevice

METRIC_POLICY = 'independent_boundaries_terminal_source_review_v3'


@dataclass
class Contact:
    id: int
    epoch: int
    label: str
    side: str
    start: float
    last: float
    low: int
    high: int
    positions: list = field(default_factory=list)
    end: float | None = None
    confirmed: bool = False
    exclusion: str | None = None
    confirmed_at: float | None = None
    lift_confirmed_at: float | None = None
    observed_samples: int = 0
    peak_width_m: float = 0.0
    merged_interruptions: list = field(default_factory=list)
    has_unknown: bool = False
    edge_estimates: dict = field(default_factory=dict)
    absent_samples: int = 0
    release_start: float | None = None
    candidate_since: int | None = None
    last_reliable_sample: int | None = None
    touch_known: bool = True
    position_known: bool = True
    candidate_outcome: str = 'pending'
    isolated_clear: bool = False
    clear_before_candidate: float | None = None
    source_islands: tuple = ()
    valid_sample_intervals: list = field(default_factory=list)
    ownership_source_id: int | None = None
    ownership_unresolved_since: int | None = None
    terminal_release_evidence: dict = field(default_factory=dict)
    position_samples: list = field(default_factory=list)
    observation_wait_since: int | None = None
    observation_closed_sample: int | None = None

    @property
    def position(self):
        return median(self.positions)


class WalkingProcessor:
    OWNERSHIP_OBSERVATION_BUDGET_MS = 2000
    name = "overground_walking"
    display_mode = "地面走路"

    def __init__(self, config: WalkingConfig, device: PreparedDevice):
        self.config = config
        self.device = device
        self.positions = device.layout.positions_m
        self.contacts = []
        self.active = []
        self.epoch = 0
        self.issues = []
        self.origin = None
        self.last_time = None
        self.last_sample = device.checked_sample_index
        self.direction = 0
        self.entry_position = None
        self.exit_position = None
        self.last_occupied = None
        self.clear_since = None
        self.finished_reason = None
        self._last_label = "B"
        self._commit_cursor = 0
        self._identity_known = True
        self._recovering = False
        self._masked_contact_uncertain = False
        self._unlocalized_masked_contact = False
        self._ambiguous_now = False
        self._last_visual = -1.0
        self.timeline = []
        self._preserved_stops = []
        self._duration_censored = False
        self._duration_start_censored = False
        self._duration_start_uncertain_since = None
        self._duration_clear_upper = None
        self._narrow_candidates = []
        self._narrow_unknown = []
        self._narrow_barriers = []
        self._candidate_decisions = []
        self._previous_frame = None
        self._multiple_islands_now = False
        self._ownership_groups = []
        self._source_review_frames = deque(maxlen=SHORT_ISLAND_MS + 1)
        self._next_ownership_source = 0
        self._touch_events = {}
        self._landing_positions = {}
        self.event_audit = []
        self._committed_contacts = set()
        self._publication_closed = False

    OWNERSHIP_RULE_VERSION = 'early_local_growth_v2'

    @property
    def touch_events(self):
        return [dict(e) for e in self._touch_events.values()]

    @property
    def reliable_touch_count(self):
        return sum(e['active'] for e in self._touch_events.values())

    def _sync_touch_publications(self):
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
            if (not c.confirmed or not c.touch_known or correction
                    or problem in {'simultaneous_contacts', 'unresolved_coalescence',
                                   'unresolved_multiple_islands', 'unknown_touch_after_gap'}):
                continue
            event = {'event_id': f'{self.device.stream_id}:{c.epoch}:{c.id}',
                     'contact_id': c.id, 'epoch': c.epoch, 'touch_sample': self._event_sample(c),
                     'touch_bounds': c.edge_estimates.get('touch'),
                     'published_sample': self.last_sample, 'active': True, 'revision': 1,
                     'publication_version': 'reliable_touch_before_sequence_v1'}
            self._touch_events[c.id] = event
            self._landing_positions[c.id] = c.position
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
        barriers = []
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

    def _ownership_rule(self, group):
        sources, runs = group['sources'], group['observation_runs']
        if any(s['evidence_at_join'].get('observation_closed_sample') is not None for s in sources):
            return 'observation_budget'
        window = max(self.config.min_contact_time, self.config.confirmation_ms)
        if any(s['first_sample'] is None for s in sources):
            return 'unknown_original_time'
        first = min(s['first_sample'] for s in sources)
        evidence = [s['evidence_at_join'] for s in sources]
        if any(e.get('confirmed') for e in evidence):
            return ('independent_mature_source' if sum(bool(e.get('confirmed')) for e in evidence) > 1
                    else 'late_source_review_required')
        if sum(e.get('peak_width_m', 0) >= .08 for e in evidence) > 1:
            return 'competing_wide_sources'
        joined = min(s['joined_sample'] for s in sources)
        latest = max(s['first_sample'] for s in sources if s['joined_sample'] == joined)
        if (latest - first > window or joined - latest > window
                or any(s['first_sample'] - joined > window
                       or s['joined_sample'] - max(s['first_sample'], joined) > window
                       for s in sources if s['joined_sample'] > joined)):
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
                self._restore_attributed_owner(group)
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
            joined = min(s['joined_sample'] for s in group['sources'])
            latest = max(s['first_sample'] for s in group['sources'] if s['joined_sample'] == joined)
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
                'initial_source_onset_span_ms': latest - first,
                'initial_separate_projection_ms': joined - latest,
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
        return c.start * 1000 if 'touch' in c.edge_estimates else round(c.start * 1000)

    def _new_recovered_owner(self, group, first):
        low, high = group['islands'][0]
        return Contact(len(self.contacts), self.epoch, '', 'unknown', first / 1000,
                       group['last_sample'] / 1000, low, high,
                       [(self.positions[low] + self.positions[high]) / 2])

    def _update_recovered_owner(self, group):
        record = ownership_record(group)
        owner = self.contacts[record['owner_id']]
        if owner.candidate_outcome in {'excluded_nonstep', 'associated_fragment'}:
            return
        owner.confirmed = owner.touch_known = True
        owner.candidate_outcome = 'confirmed_contact'
        if owner.confirmed_at is None or not self._touch_events.get(owner.id, {}).get('active'):
            owner.confirmed_at = record['recovered_sample'] / 1000
        owner.observed_samples = group['observed_samples']
        owner.valid_sample_intervals = deepcopy(group['valid_sample_intervals'])
        owner.exclusion = 'unresolved_fragment_join'
        owner.position_known = False
        owner.has_unknown = True
        owner.last = group['last_sample'] / 1000
        if group['occupancy_end_sample'] is not None:
            owner.end = group['occupancy_end_sample'] / 1000
            if owner in self.active:
                self.active.remove(owner)

    def _restore_attributed_owner(self, group):
        # Only an independently established owner can regain its own shape.
        # Initial multi-source recovery still cannot establish that shape.
        record = group.get('established_owner')
        if record is None or group.get('competing_owner_ids'):
            return
        owner = self.contacts[record['owner_id']]
        if (owner.exclusion != 'unresolved_fragment_join'
                or not self._touch_events.get(owner.id, {}).get('active')
                or assigned_sources(group) != {s['source_id'] for s in group['sources']}
                or group['close_reason'] == 'observation_budget'
                or group['valid_sample_intervals'] != [[record['original_touch_sample'],group['last_sample']+1]]
                or not group['observation_runs'] or not all(r[3] for r in group['observation_runs'])
                or any(gap['reason'] != 'unresolved_fragment_join' for gap in owner.merged_interruptions)):
            return
        source = next(s for s in group['sources'] if s.get('contact_id') == owner.id)
        before = source['evidence_at_join']
        if before.get('has_unknown') or not before.get('position_known') or before.get('exclusion'):
            return
        owner.exclusion = None
        owner.position_known = True
        owner.has_unknown = False
        owner.side = before.get('side','unknown')
        owner.merged_interruptions.clear()
        if not group.get('restored_source_ids') == sorted(assigned_sources(group)):
            group['restored_source_ids'] = sorted(assigned_sources(group))
            self.event_audit.append({'action':'source_uncertainty_resolved', 'sample':self.last_sample,
                'group_id':group['id'], 'owner_id':owner.id,
                'source_ids':list(group['restored_source_ids']),
                'reason':'all_local_sources_attributed_to_established_owner'})

    def break_continuity(self, code, frame_index=None):
        self._close_ownership_groups(code, self.last_sample)
        self._preserved_stops = self._stop_intervals()
        t = self.last_time
        self.issues.append({"code": code, "time_s": t, "frame_index": frame_index})
        if self.origin is not None and t is not None:
            self.timeline.append({"timestamp_s": t - self.origin + .001, "positions_m": self.positions,
                                  "contact_bits": [0] * len(self.positions),
                                  "valid_bits": [0] * len(self.positions), "feet": [], "quality_flags": [code]})
        for contact in self.active:
            self._censor_duration_start(contact.start, contact.edge_estimates.get('touch'))
            self._close_unknown_candidate(contact, code)
            contact.exclusion = code
            contact.touch_known &= contact.confirmed
            contact.position_known = False
        for contact in self.contacts[self._commit_cursor:]:
            contact.exclusion = contact.exclusion or code
        self._commit_cursor = len(self.contacts)
        self.active.clear()
        for candidate in self._narrow_candidates:
            self._censor_duration_start(candidate['start'])
            self._record_candidate(candidate, 'unresolved', code)
        self._narrow_candidates.clear()
        self._previous_frame = None
        self.epoch += 1
        self._identity_known = False
        self._recovering = True
        self._last_label = "B"
        self.clear_since = None


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
        inherit_wait = (closed is not None or isinstance(candidate, Contact) and not candidate.confirmed
                        and candidate.peak_width_m < .08 and wait_since is not None)
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
            known_sources = {s['source_id'] for g in touched for s in g['sources']}
            rows = [self._ownership_source(c) for c in sources
                    if (c.ownership_source_id if isinstance(c, Contact) else c.get('ownership_source_id'))
                    not in known_sources]
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

    def _clusters(self, bits):
        if b'\x01' not in bits:
            return []
        groups = []
        for i in sorted(blocked_indices(bits)):
            previous = groups[-1][-1] if groups else None
            adjacent = (previous is not None and i == previous + 1
                        and self.positions[i] - self.positions[previous] <= 1.5 * max(
                            self.device.layout.segments[i // 96].pitch_m,
                            self.device.layout.segments[previous // 96].pitch_m))
            if adjacent:
                groups[-1].append(i)
            else:
                groups.append([i])
        # Keep edge fragments so incomplete entry/exit contacts cannot look complete.
        return [(g[0], g[-1]) for g in groups]

    def _associate_inner_fragments(self, groups):
        # Each fragment needs an actually blocked, valid preceding overlap;
        # an empty hole inside the old envelope is not an ownership anchor.
        owners = {}
        tracks = [(c.id, c.low, c.high) for c in self.active]
        tracks += [(-i - 1, p['low'], p['high']) for i, p in enumerate(self._narrow_candidates)]
        for index, (low, high) in enumerate(groups):
            candidates = [(owner, left, right) for owner, left, right in tracks
                          if low <= right and high >= left]
            if len(candidates) != 1:
                continue
            owner, left, right = candidates[0]
            previous = self._previous_frame
            a, b = max(low,left), min(high,right)
            overlaps_observation = (previous is not None
                and previous.sample_index == self.last_sample - 1
                and all(previous.valid_bits[a:b+1])
                and any(previous.contact_bits[a:b+1]))
            if not overlaps_observation:
                continue
            if (self.positions[low] >= self.positions[left] - .035
                    and self.positions[high] <= self.positions[right] + .035):
                owners.setdefault(owner, []).append(index)
        merged, consumed = {}, set()
        for indices in owners.values():
            if len(indices) <= 1:
                continue
            low, high = groups[indices[0]][0], groups[indices[-1]][1]
            if self.positions[high] - self.positions[low] > .45:
                continue
            merged[indices[0]] = (low, high)
            consumed.update(indices[1:])
        return [merged.get(index, group) for index, group in enumerate(groups)
                if index not in consumed]

    def _owners(self, low, high, groups=(), observation=None):
        centre = (self.positions[low] + self.positions[high]) / 2
        owners = [c for c in self.active if low <= c.high and high >= c.low]
        if owners:
            return owners
        # A censored edge moving out of an unavailable region must not become
        # a fresh known touch. This fallback carries its existing uncertainty;
        # it cannot absorb a new island while the old envelope is still seen.
        return [c for c in self.active
                if (c.exclusion in {'masked_contact_boundary', 'boundary_contact'}
                    or observation is not None and c.candidate_since is not None
                    and observation.edge(low, high, 1) is not None)
                and not any(left <= c.high and right >= c.low for left, right in groups)
                and self.positions[low] <= self.positions[c.high] + .035
                and self.positions[high] >= self.positions[c.low] - .035
                and abs((self.positions[c.low] + self.positions[c.high]) / 2 - centre) <= .18]

    def _masked_islands(self, groups):
        # A known unavailable beam is an unknown observation, not a clear
        # separator. Keep that local occupancy censored; never bridge healthy
        # clear beams or infer a foot identity from this grouping.
        result = []
        bad = set(self.device.bad_indices)
        for low, high in groups:
            if (result and low > result[-1][1] + 1
                    and all(i in bad for i in range(result[-1][1] + 1, low))):
                result[-1] = (result[-1][0], high)
            else:
                result.append((low, high))
        return result

    def _hold_overlapping_contacts(self, groups, frame):
        # A shared optical projection cannot prove either foot's observation
        # or release. Retain both tracks and their known earlier touches,
        # without voting, widening their envelopes, or reconstructing touches.
        kept, held = [], set()
        for low, high in groups:
            owners = [c for c in self.active if low <= c.high and high >= c.low]
            if (len(owners) != 2 or not all(c.confirmed or c.exclusion == 'unresolved_multiple_islands'
                                           for c in owners)):
                kept.append((low, high))
                continue
            if not all(c.exclusion == 'ambiguous_contacts' for c in owners):
                self.issues.append({'code': 'ambiguous_contacts', 'scope': 'local_overlap',
                                    'time_s': frame.sample_time_s, 'frame_index': frame.frame_index,
                                    'contact_ids': [c.id for c in owners]})
            self._identity_known = False
            for c in owners:
                c.exclusion = 'ambiguous_contacts'
                c.touch_known &= c.confirmed
                c.position_known = False
                c.has_unknown = True
                c.side = 'unknown'
                gap = c.merged_interruptions[-1] if c.merged_interruptions else None
                if gap and gap['reason'] == 'spatial_overlap' and gap['end_sample'] == frame.sample_index:
                    gap['end_sample'] += 1
                else:
                    c.merged_interruptions.append({'start_sample': frame.sample_index,
                                                  'end_sample': frame.sample_index + 1,
                                                  'reason': 'spatial_overlap'})
                c.last = frame.sample_time_s
                c.release_start = None
                c.absent_samples = 0
                held.add(c.id)
        return kept, held

    def _local_clear(self, frame, low, high):
        # Use the existing association margin. A masked neighbour or field
        # boundary cannot prove an isolated observation has fully released.
        left, right = low - 3, high + 3
        if frame is None or left < 0 or right >= len(self.positions):
            return False
        if any(left <= i <= right for i in self.device.bad_indices):
            return False
        return (all(frame.valid_bits[left:right + 1])
                and not any(frame.contact_bits[left:right + 1]))

    def _observe_terminal_owner(self, contact, frame, low, high, reliable):
        # A healthy overlap chain supports the existing terminal owner, not
        # foot cardinality throughout the earlier masked portion of its stance.
        if contact.exclusion != 'masked_contact_boundary':
            return
        previous = self._previous_frame
        evidence = contact.terminal_release_evidence
        if not evidence:
            evidence.update({'basis': 'healthy_terminal_release',
                             'rule_version': 'healthy_overlap_terminal_v1',
                             'owner_id': contact.id,
                             'original_touch_sample': round(contact.start * 1000),
                             'association_basis': 'unique_owner_consecutive_healthy_overlap',
                             'valid': False, 'occupancy_valid': False,
                             'association_valid': contact.confirmed and contact.touch_known,
                             'association_interval': [frame.sample_index - 1, frame.sample_index + 1]})
        shared = (previous is not None and previous.sample_index == frame.sample_index - 1
                  and any(i not in self.device.bad_indices and previous.valid_bits[i]
                          and frame.valid_bits[i] and previous.contact_bits[i] and frame.contact_bits[i]
                          for i in range(max(low, contact.low), min(high, contact.high) + 1)))
        evidence['association_valid'] &= bool(shared and reliable and not contact.has_unknown
            and not contact.merged_interruptions and not contact.edge_estimates
            and contact.ownership_unresolved_since is None)
        evidence['association_interval'][1] = frame.sample_index + 1
        evidence['clear_interval'] = None

    def _candidate_row(self, candidate, outcome, reason, closed_sample=None, owner_id=None):
        if isinstance(candidate, Contact):
            row = {'source': 'contact', 'contact_id': candidate.id, 'epoch': candidate.epoch,
                   'first_sample': round(candidate.start * 1000) if 'touch' not in candidate.edge_estimates else None,
                   'last_sample': round(candidate.last * 1000),
                   'low': candidate.low, 'high': candidate.high, 'observed_samples': candidate.observed_samples}
            clear = candidate.isolated_clear
        else:
            row = {'source': 'narrow', 'epoch': self.epoch,
                   'first_sample': round(candidate['start'] * 1000), 'last_sample': candidate['last_sample'],
                   'low': candidate['low'], 'high': candidate['high'], 'observed_samples': candidate['samples']}
            clear = candidate.get('isolated_clear', False)
        since = candidate.observation_wait_since if isinstance(candidate, Contact) else candidate.get('observation_wait_since')
        closed = candidate.observation_closed_sample if isinstance(candidate, Contact) else candidate.get('observation_closed_sample')
        if closed is not None:
            row.update(observation_wait_since=since, observation_closed_sample=closed)
        row.update(outcome=outcome, reason=reason, closed_sample=closed_sample)
        row['isolated_clear_evidence'] = clear
        if owner_id is not None:
            row['owner_id'] = owner_id
        return row

    def _record_candidate(self, candidate, outcome, reason, closed_sample=None, owner_id=None):
        row = self._candidate_row(candidate, outcome, reason, closed_sample, owner_id)
        self._candidate_decisions.append(row)
        if reason == 'observation_budget':
            self.event_audit.append({'action': 'candidate_observation_closed', 'sample': self.last_sample, **deepcopy(row)})

    def _close_unknown_candidate(self, contact, reason):
        if not contact.confirmed and contact.candidate_outcome == 'pending':
            self._censor_duration_start(contact.start, contact.edge_estimates.get('touch'))
            contact.candidate_outcome = 'unresolved'
            self._record_candidate(contact, 'unresolved', reason)

    def _immature_pair(self, candidates, low, high, sample):
        # Coalescence can justify local tracking, never a one-foot assertion.
        if (len(candidates) != 2 or low == 0 or high == len(self.positions) - 1
                or self.positions[high] - self.positions[low] > .45
                or any(low - 3 <= i <= high + 3 for i in self.device.bad_indices)):
            return None
        evidence = []
        for c in candidates:
            if isinstance(c, Contact):
                start, last = round(c.start * 1000), round(c.last * 1000)
                width, votes = c.peak_width_m, c.observed_samples
                problem = c.confirmed or c.exclusion or c.has_unknown or c.merged_interruptions
                left, right = c.low, c.high
            else:
                start, last = round(c['start'] * 1000), c['last_sample']
                left, right = c['low'], c['high']
                width, votes = c['peak_width_m'], c['samples']
                problem = c.get('masked_contact') or c.get('coalesced') or c['merged_interruptions']
            if (problem or width >= .035 or last != sample - 1 or votes != last - start + 1
                    or low > left or high < right):
                return None
            evidence.append((start, c))
        evidence.sort(key=lambda item: item[0])
        a, b = evidence
        if not 0 < b[0] - a[0] <= self.config.confirmation_ms or sample - a[0] > self.config.confirmation_ms:
            return None
        return a[1], b[1]

    def _coalesce_immature_contacts(self, groups, sample):
        for low, high in groups:
            candidates = [c for c in self.active if low <= c.high and high >= c.low]
            pair = self._immature_pair(candidates, low, high, sample)
            if pair is None:
                # A real connected observation may cover several unfinished
                # sources. Track its occupancy locally, without declaring
                # those sources one foot or discarding a remote contact.
                if (len(candidates) > 1 and not all(c.confirmed for c in candidates)
                        and self.positions[high] - self.positions[low] <= .45):
                    known = [c for c in candidates if c.confirmed]
                    owner = known[0] if known else min(candidates, key=lambda c: c.start)
                    self.issues.append({'code': 'ambiguous_contacts', 'scope': 'local_sources_connected',
                                        'time_s': sample / 1000, 'frame_index': sample})
                    self._identity_known = False
                    for c in candidates:
                        if c is not owner:
                            self._record_candidate(c, 'unresolved', 'sources_connected', sample, owner.id)
                            c.candidate_outcome = 'unresolved_source'
                            c.exclusion = 'unresolved_coalescence'
                            c.touch_known = c.position_known = False
                            c.has_unknown = True
                            c.side = 'unknown'
                            self.active.remove(c)
                        self._censor_duration_start(c.start)
                    owner.exclusion = 'unresolved_fragment_join' if owner.confirmed else 'unresolved_coalescence'
                    owner.touch_known &= owner.confirmed
                    owner.position_known = False
                    owner.has_unknown = True
                    owner.side = 'unknown'
                    owner.merged_interruptions.append({
                        'start_sample': round(min(c.start for c in candidates) * 1000),
                        'end_sample': sample + 1, 'reason': 'unresolved_fragment_join'})
                continue
            a, b = pair
            self._record_candidate(b, 'associated_fragment', 'immature_islands_coalesced', sample, a.id)
            b.candidate_outcome = 'associated_fragment'
            self.active.remove(b)
            for c in pair:
                c.exclusion = 'unresolved_coalescence'
                c.touch_known = c.position_known = False
                c.has_unknown = True
                c.side = 'unknown'
            self._identity_known = False
            self._censor_duration_start(a.start)
            self._narrow_unknown.append((a.start, sample / 1000))

    def _local_pending_pair(self, pending, groups, owners, low, high, sample):
        # Preserve a remote reliable foot while two local, still unconfirmed
        # sources grow together. This group does not establish foot identity.
        if (len(pending) != 2 or len(groups) != 2 or len(self.active) != 1
                or sum(bool(cs) for cs in owners) != 1
                or low == 0 or high == len(self.positions) - 1
                or not .08 <= self.positions[high] - self.positions[low] <= .45
                or any(low - 3 <= i <= high + 3 for i in self.device.bad_indices)):
            return None
        anchor = self.active[0]
        if (not anchor.confirmed or anchor.exclusion or anchor.has_unknown
                or not anchor.touch_known or not anchor.position_known
                or round(anchor.last * 1000) != sample - 1 or anchor.release_start is not None):
            return None
        ordered = sorted(pending, key=lambda p: p['start'])
        if ordered[0]['start'] == ordered[1]['start']:
            return None
        for p in ordered:
            start = round(p['start'] * 1000)
            if (p['last_sample'] != sample - 1 or p['samples'] != sample - start
                    or sample - start >= max(self.config.min_contact_time, self.config.confirmation_ms)
                    or p['peak_width_m'] >= .08 or p.get('masked_contact')
                    or p.get('coalesced') or p['merged_interruptions']
                    or low > p['low'] or high < p['high']):
                return None
        return ordered

    def process(self, frame, observation=None, *, masked_contact=False):
        if self.finished_reason:
            return
        if observation is not None:
            frame = observation.measurement_frame()
        if frame.stream_id != self.device.stream_id or frame.layout != self.device.layout:
            self.break_continuity("device_changed", frame.frame_index)
            self.finished_reason = "device_changed"
            return
        if frame.sample_index <= self.last_sample:
            self.break_continuity("counter_reset", frame.frame_index)
            self.finished_reason = "counter_reset"
            return
        if frame.sample_index != self.last_sample + 1 or frame.dropped_frames_before:
            self.break_continuity("frame_gap", frame.frame_index)
        self.last_sample = frame.sample_index
        if (len(frame.contact_bits) != len(self.positions)
                or len(frame.valid_bits) != len(self.positions)
                or (observation is None and not all(frame.valid_bits))
                or any(flag != "frame_gap" for flag in frame.quality_flags)):
            self.break_continuity("invalid_sample", frame.frame_index)
            return
        sample_time = frame.sample_time_s
        self.last_time = sample_time
        affected = [(low, high) for low, high in self._clusters(frame.contact_bits) if any(
            low - 1 <= i <= high + 1
            and self.positions[low] - .04 <= self.positions[i] <= self.positions[high] + .04
            for i in self.device.bad_indices)] if masked_contact else []
        if masked_contact:
            self._duration_censored = True
            self._duration_clear_upper = None
            self._censor_duration_start(sample_time)
            if not affected:
                # A caller without a localized quality snapshot still cannot
                # support continuity across an unspecified missing observation.
                if not self._unlocalized_masked_contact:
                    self.break_continuity("masked_contact_boundary", frame.frame_index)
                self._unlocalized_masked_contact = True
                self._masked_contact_uncertain = True
                return
            if not self._masked_contact_uncertain:
                self.issues.append({"code": "masked_contact_boundary", "time_s": sample_time,
                                    "frame_index": frame.frame_index})
            self._identity_known = False
        self._unlocalized_masked_contact = False
        self._masked_contact_uncertain = masked_contact
        if observation is not None and observation.unresolved_segments:
            self._duration_censored = True
            self._duration_clear_upper = None
        if (self._duration_censored and self._duration_clear_upper is None
                and b'\x01' not in frame.contact_bits and b'\x00' not in frame.valid_bits):
            self._duration_clear_upper = frame.sample_index
        if observation is not None:
            for contact in list(self.active):
                if observation.affected(contact.low, contact.high):
                    self._preserved_stops = self._stop_intervals()
                    self._close_unknown_candidate(contact, 'local_unknown_timeout')
                    contact.exclusion = 'local_unknown_timeout'
                    self.active.remove(contact)
                    self._identity_known = False
            for contact in list(self.active):
                if (contact.exclusion != 'local_unknown_timeout' and not contact.confirmed and contact.has_unknown
                        and frame.sample_index - contact.start * 1000 >=
                        max(self.config.min_contact_time, self.config.confirmation_ms) + 10):
                    self._close_unknown_candidate(contact, 'local_unknown_timeout')
                    contact.exclusion = 'local_unknown_timeout'
                    self._identity_known = False
                elif (contact.exclusion != 'local_unknown_timeout' and contact.candidate_since is not None
                      and frame.sample_index - contact.candidate_since >= self.config.release_ms + 10):
                    self._preserved_stops = self._stop_intervals()
                    self._close_unknown_candidate(contact, 'local_unknown_timeout')
                    contact.exclusion = 'local_unknown_timeout'
                    self._identity_known = False
        # Expire absence before association, including a return exactly at the
        # release threshold. The edge remains the first absent device sample.
        for contact in list(self.active):
            if not contact.confirmed and sample_time > contact.last:
                contact.isolated_clear &= observation is None and self._local_clear(frame, contact.low, contact.high)
            absent_start = contact.release_start if contact.release_start is not None else contact.last + .001
            released = (sample_time > absent_start + 1e-9
                        and sample_time - absent_start + 1e-9 >= self.config.release_ms / 1000)
            if observation is not None:
                released = (contact.absent_samples >= self.config.release_ms
                            and observation.release_reliable(contact.low, contact.high,
                                                            3 * self.device.layout.segments[contact.high // 96].pitch_m))
            if released:
                terminal = contact.terminal_release_evidence
                suffix = contact.valid_sample_intervals[-1] if contact.valid_sample_intervals else None
                terminal_valid = (contact.exclusion == 'masked_contact_boundary' and terminal
                    and terminal['association_valid'] and not contact.has_unknown
                    and not contact.merged_interruptions and not contact.edge_estimates
                    and suffix is not None and suffix[1] == round(absent_start * 1000)
                    and suffix[1] - suffix[0] >= max(1, self.config.confirmation_ms)
                    and terminal['clear_interval'] == [round(absent_start * 1000), frame.sample_index]
                    and self._local_clear(frame, contact.low, contact.high)
                    and (observation is None or observation.release_reliable(contact.low, contact.high,
                         3 * self.device.layout.segments[contact.high // 96].pitch_m)))
                if terminal_valid:
                    terminal.update({'valid': True, 'missing_reason': None,
                                     'healthy_suffix_interval': list(suffix),
                                     'required_healthy_samples': max(1, self.config.confirmation_ms),
                                     'checked_beams': [contact.low - 3, contact.high + 3],
                                     'clear_interval': [round(absent_start * 1000), frame.sample_index + 1],
                                     'lift_sample': round(absent_start * 1000),
                                     'confirmed_sample': frame.sample_index})
                if contact.exclusion != 'masked_contact_boundary' or terminal_valid:
                    contact.end = absent_start
                    contact.lift_confirmed_at = sample_time
                if (not contact.confirmed
                        or absent_start - contact.start + 1e-9 < self.config.min_contact_time / 1000):
                    excluded = (not contact.confirmed and not contact.exclusion and contact.isolated_clear
                                and contact.observed_samples == 1 and contact.peak_width_m == 0
                                and not contact.merged_interruptions and not contact.has_unknown)
                    previous_outcome = contact.candidate_outcome
                    contact.candidate_outcome = 'excluded_nonstep' if excluded else 'unresolved'
                    contact.exclusion = contact.exclusion or ('excluded_nonstep' if excluded else 'short_contact')
                    if previous_outcome != 'unresolved':
                        self._record_candidate(contact, contact.candidate_outcome,
                                               'closed_isolated_single_sample' if excluded else contact.exclusion,
                                               frame.sample_index)
                    if excluded and self.last_occupied == contact.last:
                        self.last_occupied = max((c.last for c in self.contacts
                                                  if c.candidate_outcome != 'excluded_nonstep'
                                                  and c.exclusion != 'masked_contact_boundary'), default=None)
                        clear_starts = [c.clear_before_candidate for c in self.contacts
                                        if c.epoch == self.epoch and c.candidate_outcome == 'excluded_nonstep'
                                        and c.clear_before_candidate is not None
                                        and not any(issue['time_s'] is not None
                                                    and issue['time_s'] >= c.clear_before_candidate for issue in self.issues)]
                        if clear_starts and self.last_occupied is not None:
                            self.clear_since = max(min(clear_starts), self.last_occupied + .001)
                    if not excluded:
                        self._censor_duration_start(contact.start, contact.edge_estimates.get('touch'))
                        self._identity_known = False
                        for later in self.contacts[contact.id + 1:]:
                            later.side = "unknown"
                self.active.remove(contact)
        groups = self._clusters(frame.contact_bits)
        source_islands = tuple(groups)
        # Known bad beams censor their neighbouring footprint, not a remote
        # foot's observable touch. Keep tracking the affected owner so its
        # later visible fragment cannot be counted as another landing.
        if observation is None:
            if masked_contact:
                groups = self._masked_islands(groups)
        self._observe_ownership_groups(source_islands, frame, observation)
        groups = self._associate_inner_fragments(groups)
        groups, held = self._hold_overlapping_contacts(groups, frame)
        if observation is None:
            self._coalesce_immature_contacts(groups, frame.sample_index)
        source_multiple_islands = len(groups) > 2
        seeds, candidate_ambiguity = {}, False
        if observation is None:
            groups, seeds, candidate_ambiguity = self._defer_narrow_candidates(groups, frame, affected)
        matches = []
        used = set()
        ambiguous = candidate_ambiguity
        for low, high in groups:
            centre = (self.positions[low] + self.positions[high]) / 2
            candidates = self._owners(low, high, groups, observation)
            if len(candidates) > 1 or (candidates and candidates[0].id in used):
                ambiguous = True
            if self.positions[high] - self.positions[low] > .45:
                ambiguous = True
            contact = candidates[0] if len(candidates) == 1 else None
            if contact:
                used.add(contact.id)
            matches.append((low, high, centre, contact))
        multiple_islands = source_multiple_islands and any(c is None for _, _, _, c in matches)
        if multiple_islands:
            # Extra islands can make ordering uncertain, but do not revoke a
            # remote source's own observations or observed touchdown boundary.
            self._identity_known = False
            if not self._multiple_islands_now:
                self.issues.append({'code': 'ambiguous_contacts', 'scope': 'local_multiple_islands',
                                    'time_s': sample_time, 'frame_index': frame.frame_index})
        self._multiple_islands_now = multiple_islands
        if ambiguous:
            self._censor_duration_start(sample_time)
            if not self._ambiguous_now:
                self.break_continuity("ambiguous_contacts", frame.frame_index)
            else:
                for c in self.active:
                    c.exclusion = "ambiguous_contacts"
                self.active.clear()
            self._ambiguous_now = True
            self._record_visual(frame)
            return
        self._ambiguous_now = False

        new_contacts = []
        for low, high, centre, contact in matches:
            if (contact is not None and observation is not None
                    and not (low <= contact.high and high >= contact.low)):
                contact.exclusion = 'unresolved_fragment_join'
                contact.touch_known &= contact.confirmed
                contact.position_known = False
                contact.has_unknown = True
                contact.side = 'unknown'
                self._identity_known = False
                contact.merged_interruptions.append({'start_sample': contact.candidate_since
                                                     if contact.candidate_since is not None else frame.sample_index,
                                                     'end_sample': frame.sample_index + 1,
                                                     'reason': 'unresolved_fragment_join'})
            if contact is not None and abs((self.positions[contact.low] + self.positions[contact.high]) / 2 - centre) > .18:
                contact.exclusion = 'unresolved_fragment_join'
                contact.touch_known &= contact.confirmed
                contact.position_known = False
                contact.has_unknown = True
                contact.side = 'unknown'
                self._identity_known = False
                contact.merged_interruptions.append({'start_sample': frame.sample_index,
                                                     'end_sample': frame.sample_index + 1,
                                                     'reason': 'unresolved_fragment_join'})
            if contact is None:
                contact = Contact(len(self.contacts), self.epoch, "", "unknown", sample_time,
                                  sample_time, low, high, [centre])
                contact.observation_wait_since = frame.sample_index
                contact.clear_before_candidate = self.clear_since
                seed = seeds.get((low, high))
                if seed:
                    contact.start = seed['start']
                    contact.observed_samples = seed['samples'] - 1
                    contact.valid_sample_intervals = [list(x) for x in seed.get('valid_sample_intervals', [])]
                    contact.ownership_source_id = seed.get('ownership_source_id')
                    contact.ownership_unresolved_since = seed.get('ownership_unresolved_since')
                    contact.observation_wait_since = seed.get('observation_wait_since', frame.sample_index)
                    contact.observation_closed_sample = seed.get('observation_closed_sample')
                    contact.positions = list(seed.get('positions', [seed['centre']]))
                    contact.position_samples = deepcopy(seed.get('position_samples', []))
                    contact.merged_interruptions = list(seed.get('merged_interruptions', ()))
                    contact.isolated_clear = seed.get('isolated_clear', False)
                    if seed.get('masked_contact'):
                        contact.exclusion = 'masked_contact_boundary'
                        contact.touch_known = contact.position_known = False
                    if seed.get('coalesced'):
                        contact.exclusion = 'unresolved_coalescence'
                        contact.touch_known = contact.position_known = False
                        contact.has_unknown = True
                else:
                    contact.isolated_clear = (observation is None and not self._recovering
                                              and self._previous_frame is not None
                                              and self._previous_frame.sample_index == frame.sample_index - 1
                                              and self._local_clear(self._previous_frame, low, high))
                if self._recovering:
                    contact.exclusion = "unknown_touch_after_gap"
                    contact.touch_known = False
                if observation is not None:
                    edge = observation.edge(low, high, 1)
                    if edge:
                        contact.start = edge.sample / 1000
                        contact.edge_estimates['touch'] = [edge.left_sample, edge.right_sample]
                    recovering_source = observation.affected(low, high, observation.recovery_segments)
                    if recovering_source:
                        contact.exclusion = 'unknown_touch_after_gap'
                        contact.touch_known = False
                    if edge or recovering_source:
                        # A new estimated or recovering island beside an old
                        # edge may continue that foot through the unknown seam.
                        # Keep separate sources without proving a new foot.
                        neighbours = [c for c in self.active
                                      if (recovering_source or observation.neighbour_unknown(c.low, c.high, .035))
                                      and self.positions[low] <= self.positions[c.high] + .035
                                      and self.positions[high] >= self.positions[c.low] - .035]
                        if neighbours:
                            self._identity_known = False
                            for c in [*neighbours, contact]:
                                c.exclusion = 'unresolved_fragment_join'
                                c.touch_known &= c.confirmed
                                c.position_known = False
                                c.has_unknown = True
                                c.side = 'unknown'
                                c.merged_interruptions.append({'start_sample': edge.left_sample if edge
                                                               else frame.sample_index,
                                                               'end_sample': frame.sample_index + 1,
                                                               'reason': 'unresolved_fragment_join'})
                self.contacts.append(contact)
                self.active.append(contact)
                new_contacts.append(contact)
            elif sample_time - contact.last > .001 + 1e-9 and contact.release_start is not None:
                contact.merged_interruptions.append({
                    "start_sample": round(contact.last * 1000) + 1,
                    "end_sample": frame.sample_index, "reason": "release_debounce",
                })
            contact.last = sample_time
            if (contact.merged_interruptions
                    and contact.merged_interruptions[-1]['reason'] == 'unresolved_fragment_join'):
                contact.merged_interruptions[-1]['end_sample'] = frame.sample_index + 1
            simultaneous = (any(c is not contact and c.start == contact.start for c in self.active)
                            or any(p['start'] == contact.start for p in self._narrow_candidates))
            third_source = (contact in new_contacts and sum(
                c is not None and c.confirmed and c.touch_known and not c.exclusion
                for _, _, _, c in matches) >= 2)
            if multiple_islands and not contact.confirmed and (simultaneous or third_source):
                contact.exclusion = 'unresolved_multiple_islands'
                contact.touch_known = contact.position_known = False
                contact.has_unknown = True
                contact.side = 'unknown'
                contact.ownership_unresolved_since = contact.ownership_unresolved_since or frame.sample_index
                for p in self._narrow_candidates:
                    if p['start'] == contact.start:
                        p['coalesced'] = True
                        p.setdefault('ownership_unresolved_since', frame.sample_index)
            if any(low <= right and high >= left for left, right in affected):
                contact.exclusion = 'masked_contact_boundary'
                contact.touch_known &= contact.confirmed
                contact.position_known = False
            reliable = observation is None or observation.reliable(low, high)
            self._observe_terminal_owner(contact, frame, low, high, reliable)
            contact.observed_samples += int(reliable and contact.exclusion != 'local_unknown_timeout')
            if (reliable and contact.exclusion != 'local_unknown_timeout'
                    and not any(low <= right and high >= left for left, right in affected)):
                self._observe_source(contact.valid_sample_intervals, frame.sample_index)
            if reliable:
                contact.last_reliable_sample = frame.sample_index
            if reliable:
                contact.absent_samples = 0
                contact.release_start = None
                contact.candidate_since = None
            contact.low, contact.high = low, high
            contact.source_islands = tuple((left, right) for left, right in source_islands
                                           if low <= left and high >= right)
            if reliable:
                contact.peak_width_m = max(contact.peak_width_m, self.positions[high] - self.positions[low])
            if observation is not None:
                contact.has_unknown |= observation.affected(low, high, observation.unknown_segments) or bool(observation.edge(low, high, 1))
            if not contact.position_samples or frame.sample_index % 20 == 0:
                record_centre_sample(contact.position_samples, frame, low, high,
                                     self.device.bad_indices, observation)
            # Bounded spatial history, sampled every 20 ms; stance roll is not travel.
            if reliable and len(contact.positions) < 100 and frame.sample_index % 20 == 0:
                contact.positions.append(centre)
            if low == 0 or high == len(self.positions) - 1:
                contact.exclusion = contact.exclusion or "boundary_contact"
                if contact.start == sample_time:
                    contact.touch_known = False
                contact.position_known = False
            if not contact.touch_known:
                self._censor_duration_start(contact.start, contact.edge_estimates.get('touch'))
            wide_enough = contact.peak_width_m >= .08 or contact.exclusion == "boundary_contact"
            if (contact.exclusion != 'local_unknown_timeout' and not contact.confirmed and wide_enough
                    and contact.observation_closed_sample is None
                    and contact.observed_samples >= self.config.confirmation_ms
                    and sample_time - contact.start + .001 + 1e-9 >= self.config.min_contact_time / 1000):
                contact.confirmed = True
                contact.candidate_outcome = 'confirmed_contact'
                contact.confirmed_at = sample_time

        matched = {c.id for _, _, _, c in matches if c is not None}
        matched.update(c.id for c in new_contacts)
        matched.update(held)
        for contact in self.active:
            if contact.id in held:
                contact.source_islands = tuple((left, right) for left, right in source_islands
                                               if left <= contact.high and right >= contact.low)
        for contact in list(self.active):
            if contact.id in matched:
                continue
            if contact.exclusion == 'local_unknown_timeout':
                if observation.reliable(contact.low, contact.high):
                    self.active.remove(contact)
                continue
            reliable = observation is None or observation.release_reliable(
                contact.low, contact.high, 3 * self.device.layout.segments[contact.high // 96].pitch_m)
            terminal = contact.terminal_release_evidence
            if terminal:
                interval = terminal['clear_interval']
                terminal['clear_interval'] = ([interval[0] if interval and interval[1] == frame.sample_index
                                               else frame.sample_index, frame.sample_index + 1]
                    if reliable and self._local_clear(frame, contact.low, contact.high) else None)
            edge = observation.edge(contact.low, contact.high, 0) if observation is not None else None
            if (observation is not None and observation.neighbour_unknown(
                    contact.low, contact.high, 3 * self.device.layout.segments[contact.high // 96].pitch_m)):
                edge = None
            if observation is not None and contact.candidate_since is None:
                contact.candidate_since = frame.sample_index
            if contact.release_start is None and (reliable or edge):
                contact.release_start = contact.last + .001
                if (observation is not None and not edge
                        and frame.sample_index > contact.candidate_since):
                    left = contact.last_reliable_sample
                    if left is None or frame.sample_index - left > 11:
                        self._preserved_stops = self._stop_intervals()
                        self._close_unknown_candidate(contact, 'local_unknown_timeout')
                        contact.release_start = None
                        contact.exclusion = 'local_unknown_timeout'
                        self.active.remove(contact)
                        self._identity_known = False
                        continue
                    contact.release_start = (left + frame.sample_index) / 2000
                    contact.edge_estimates['lift'] = [left, frame.sample_index]
            if edge:
                contact.release_start = edge.sample / 1000
                contact.edge_estimates['lift'] = [edge.left_sample, edge.right_sample]
            if observation is not None and reliable:
                contact.absent_samples += 1

        if len(new_contacts) > 1:
            for c in new_contacts:
                c.ownership_unresolved_since = frame.sample_index
                c.exclusion = c.exclusion or "simultaneous_contacts"
                c.touch_known = False
                self._censor_duration_start(c.start, c.edge_estimates.get('touch'))
            self._identity_known = False
        self._recover_ownership_groups()
        self._commit_contacts()
        # Existing footprints immediately after a gap have unknown touch times.
        # Later new contacts can be measured, with a new A/B identity epoch.
        self._recovering = False
        if b'\x01' in frame.contact_bits:
            if any(c.id in matched and c.exclusion != 'masked_contact_boundary' for c in self.active):
                self.last_occupied = sample_time
            self.clear_since = None
        elif observation is not None and observation.unresolved_segments:
            self.clear_since = None
        elif self.origin is not None:
            if self.clear_since is None:
                self.clear_since = sample_time
            if self.config.has_auto_stop and sample_time - self.clear_since >= self.config.exit_clear_ms / 1000:
                if self._at_exit():
                    self.finished_reason = "passage_complete"
        self._record_visual(frame)
        self._previous_frame = frame

    def _defer_narrow_candidates(self, groups, frame, affected=()):
        # A narrow, unconfirmed island is not yet another foot. Preserve its
        # spatial owners while a locally isolated island grows or releases.
        # Promotion uses the existing width/time requirements and retains its
        # original touch and reliable observations; it never fills beam bits.
        t = frame.sample_time_s
        pending, unresolved = [], []
        for p in self._narrow_candidates:
            p['isolated_clear'] &= self._local_clear(frame, p['low'], p['high'])
            if frame.sample_index < p['last_sample'] + 1 + self.config.release_ms:
                pending.append(p)
                continue
            excluded = (p['samples'] == 1 and p['low'] == p['high'] and p['isolated_clear']
                        and not p.get('masked_contact') and not p.get('merged_interruptions'))
            self._record_candidate(p, 'excluded_nonstep' if excluded else 'unresolved',
                                   'closed_isolated_single_sample' if excluded else 'short_narrow_contact',
                                   frame.sample_index)
            if not excluded:
                self._censor_duration_start(p['start'])
                unresolved.append(p)
        self._narrow_unknown.extend((p['start'], p['last'] + .001) for p in unresolved)
        self._narrow_barriers.extend((p['start'], p['last'] + .001) for p in unresolved
                                     if p.get('observation_closed_sample') is None)
        if unresolved:
            self._identity_known = False
            for c in self.contacts:
                if any(c.start >= p['start'] for p in unresolved):
                    c.side = 'unknown'
        owners = []
        for low, high in groups:
            owners.append(self._owners(low, high, groups))
        anchored = any(len(cs) == 1 and cs[0].confirmed
                       and cs[0].exclusion in {None, 'simultaneous_contacts', 'unresolved_coalescence'} for cs in owners)
        independent_wide = bool(pending) and any(not cs and self.positions[high] - self.positions[low] >= .08
                           and not any(low <= p['high'] and high >= p['low'] for p in pending)
                           for (low, high), cs in zip(groups, owners))
        if independent_wide:
            # Do not let a later independent foot overtake an earlier unresolved
            # touch. Restore normal candidate/ambiguity handling for this frame.
            anchored = False
        kept, seeds, touched, ambiguous = [], {}, set(), False
        for (low, high), cs in zip(groups, owners):
            candidates = [p for p in pending if low <= p['high'] and high >= p['low']]
            if not candidates:
                candidates = [p for p in pending if p.get('masked_contact')
                              and not any(left <= p['high'] and right >= p['low'] for left, right in groups)
                              and self.positions[low] <= self.positions[p['high']] + .035
                              and self.positions[high] >= self.positions[p['low']] - .035]
            if cs:
                kept.append((low, high))
                immature = len(cs) == 1 and not cs[0].confirmed and candidates
                unresolved_connection = False
                if immature:
                    pair = self._immature_pair([cs[0], *candidates], low, high, frame.sample_index)
                    contact = cs[0]
                    if pair is None or not isinstance(pair[0], Contact):
                        unresolved_connection = True
                        # Retain an unknown source relation rather than
                        # restarting every contact when growth connects it.
                        self.issues.append({'code': 'ambiguous_contacts', 'scope': 'local_sources_connected',
                                            'time_s': t, 'frame_index': frame.frame_index})
                        contact.start = min(contact.start, *(p['start'] for p in candidates))
                    contact.exclusion = 'unresolved_coalescence'
                    contact.touch_known = contact.position_known = False
                    contact.has_unknown = True
                    contact.side = 'unknown'
                    self._identity_known = False
                    self._censor_duration_start(contact.start)
                    self._narrow_unknown.append((contact.start, t))
                # It has joined an existing footprint rather than establishing
                # an independently observable contact.
                self._narrow_unknown.extend((p['start'], p['last'] + .001) for p in candidates)
                for p in candidates:
                    self._record_candidate(p, 'associated_fragment' if immature and not unresolved_connection else 'unresolved',
                                           'sources_connected' if unresolved_connection else
                                           'immature_islands_coalesced' if immature else 'joined_existing_footprint',
                                           frame.sample_index, cs[0].id if len(cs) == 1 else None)
                if candidates and not immature:
                    self._identity_known = False
                    for c in cs:
                        c.exclusion = c.exclusion or 'unresolved_fragment_join'
                        c.position_known = False
                        c.has_unknown = True
                        c.side = 'unknown'
                        c.merged_interruptions.append({
                            'start_sample': round(min(p['start'] for p in candidates) * 1000),
                            'end_sample': frame.sample_index + 1, 'reason': 'unresolved_fragment_join'})
                if any(p.get('masked_contact') for p in candidates):
                    for c in cs:
                        c.exclusion = 'masked_contact_boundary'
                        c.touch_known &= c.confirmed
                        c.position_known = False
                touched.update(id(p) for p in candidates)
                continue
            if len(candidates) > 1:
                pair = self._immature_pair(candidates, low, high, frame.sample_index)
                local_unresolved = False
                general_connection = False
                if pair is None:
                    pair = self._local_pending_pair(pending, groups, owners, low, high, frame.sample_index)
                    local_unresolved = pair is not None
                if pair is None:
                    if (self.positions[high] - self.positions[low] <= .45
                            and all(low <= p['low'] and high >= p['high'] for p in candidates)):
                        pair = sorted(candidates, key=lambda p: p['start'])[:2]
                        general_connection = True
                        self.issues.append({'code': 'ambiguous_contacts', 'scope': 'local_sources_connected',
                                            'time_s': t, 'frame_index': frame.sample_index})
                        local_unresolved = True
                    else:
                        kept.append((low, high))
                        ambiguous = True
                        continue
                a, b = pair
                for extra in candidates:
                    if extra is not a and extra is not b:
                        self._record_candidate(extra, 'unresolved', 'sources_connected', frame.sample_index)
                        touched.add(id(extra))
                self._record_candidate(b, 'unresolved' if local_unresolved else 'associated_fragment',
                                       'sources_connected' if general_connection else
                                       'unresolved_islands_coalesced' if local_unresolved else 'immature_islands_coalesced',
                                       frame.sample_index)
                self._candidate_decisions[-1]['owner_first_sample'] = round(a['start'] * 1000)
                touched.add(id(b))
                a['coalesced'] = True
                self._narrow_unknown.append((a['start'], t))
                self._identity_known = False
                self._censor_duration_start(a['start'])
                candidates = [a]
            p = candidates[0] if candidates else None
            width = self.positions[high] - self.positions[low]
            isolated_gate = (not anchored and low == high and any(len(owner) == 1 for owner in owners)
                             and not self._recovering and self._previous_frame is not None
                             and self._previous_frame.sample_index == frame.sample_index - 1
                             and self._local_clear(self._previous_frame, low, high))
            if p is None and (anchored or isolated_gate) and width < .08 and low != 0 and high != len(self.positions)-1:
                p = {'start': t, 'last': t, 'low': low, 'high': high, 'samples': 0,
                     'peak_width_m': width,
                     'last_sample': frame.sample_index - 1,
                     'centre': (self.positions[low] + self.positions[high]) / 2,
                     'isolated_clear': (not self._recovering and self._previous_frame is not None
                                        and self._previous_frame.sample_index == frame.sample_index - 1
                                        and self._local_clear(self._previous_frame, low, high)),
                     'merged_interruptions': [], 'position_samples': [],
                     'observation_wait_since': frame.sample_index}
                p['isolated_gate'] = isolated_gate
                p['positions'] = [p['centre']]
                pending.append(p)
            if p is None:
                kept.append((low, high))
                continue
            if p['samples'] and frame.sample_index > p['last_sample'] + 1:
                p['merged_interruptions'].append({'start_sample': p['last_sample'] + 1,
                                                  'end_sample': frame.sample_index, 'reason': 'release_debounce'})
            p.update(last=t, last_sample=frame.sample_index, low=low, high=high, samples=p['samples'] + 1)
            if not p.get('position_samples') or frame.sample_index % 20 == 0:
                record_centre_sample(p.setdefault('position_samples', []), frame, low, high,
                                     self.device.bad_indices)
            if not any(low <= right and high >= left for left, right in affected):
                self._observe_source(p.setdefault('valid_sample_intervals', []), frame.sample_index)
            p['peak_width_m'] = max(p['peak_width_m'], width)
            p['masked_contact'] = p.get('masked_contact', False) or any(
                low <= right and high >= left for left, right in affected)
            if (p.get('observation_closed_sample') is None and (not anchored and (not p.get('isolated_gate') or independent_wide)
                    or width >= .08 or low == 0 or high == len(self.positions)-1
                    or t - p['start'] + .001 + 1e-9 >=
                    max(self.config.min_contact_time, self.config.confirmation_ms) / 1000)):
                kept.append((low, high))
                seeds[(low, high)] = p
                touched.add(id(p))
            elif ('positions' in p and len(p['positions']) < 100 and frame.sample_index % 20 == 0):
                p['positions'].append((self.positions[low] + self.positions[high]) / 2)
        self._narrow_candidates = [p for p in pending if id(p) not in touched]
        return kept, seeds, ambiguous

    def _censor_duration_start(self, start, touch_bounds=None):
        if self.origin is None:
            if touch_bounds is not None:
                start = min(start, touch_bounds[0] / 1000)
            self._duration_start_censored = True
            if self._duration_start_uncertain_since is None or start < self._duration_start_uncertain_since:
                self._duration_start_uncertain_since = start

    def _commit_contacts(self):
        self._close_observation_waits()
        self._sync_touch_publications()
        ordered = sorted(self.contacts, key=lambda c: (c.start, c.id))
        for contact in ordered:
            if contact.id in self._committed_contacts:
                continue
            if any(p['start'] < contact.start and p.get('observation_closed_sample') is None for p in self._narrow_candidates):
                break
            if (self._pending_group_before(contact)
                    or (not self._publication_closed and not contact.confirmed and contact.end is None
                        and contact in self.active and contact.candidate_outcome != 'associated_fragment'
                        and contact.observation_closed_sample is None
                        and not any(g['state'] == 'closed_unknown' and any(
                            x['source_id'] == contact.ownership_source_id for x in g['sources'])
                            for g in self._ownership_groups))):
                break
            self._committed_contacts.add(contact.id)
            self._commit_cursor = len(self._committed_contacts)
            event = self._touch_events.get(contact.id)
            if event is None or not event['active']:
                if contact.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}:
                    self._identity_known = False
                continue
            prior = next((x for x in reversed(ordered)
                                if x.epoch == contact.epoch and x.label
                                and (x.start, x.id) < (contact.start, contact.id)), None)
            closed_onsets = [x.start for x in ordered if x.epoch == contact.epoch and x.observation_closed_sample is not None]
            closed_onsets += [p['start'] for p in self._narrow_candidates if p.get('observation_closed_sample') is not None]
            closed_onsets += [d['first_sample']/1000 for d in self._candidate_decisions if d['epoch'] == contact.epoch
                and d['source'] == 'narrow' and d.get('observation_closed_sample') is not None]
            closed_onsets += [(s['first_sample'] if s['first_sample'] is not None else g['unresolved_since_sample'])/1000
                for g in self._ownership_groups if g['epoch'] == contact.epoch and g['close_reason'] == 'observation_budget'
                for s in g['sources'] if s['source_id'] not in assigned_sources(g)
                and not self._touch_events.get(s.get('contact_id'), {}).get('active')]
            gap = prior is not None and any(prior.start < onset <= contact.start for onset in closed_onsets)
            if gap:
                self._identity_known = False
            prior_label = prior.label if prior is not None and not gap else 'B'
            self._last_label = 'A' if prior_label == 'B' else 'B'
            contact.label = self._last_label
            self.event_audit.append({'action': 'sequence_commit', 'sample': self.last_sample,
                'event_id': event['event_id'], 'touch_sample': event['touch_sample'], 'label': contact.label})
            first_side = {"Left": "left", "Right": "right"}.get(self.config.starting_foot)
            if first_side and self._identity_known:
                contact.side = first_side if contact.label == "A" else ("right" if first_side == "left" else "left")
            if self.origin is None:
                self.origin = contact.start
                touch_upper = contact.edge_estimates.get('touch', [contact.start * 1000] * 2)[1] / 1000
                if (contact.touch_known and self._duration_start_uncertain_since is not None
                        and touch_upper < self._duration_start_uncertain_since):
                    self._duration_start_censored = False
            if not contact.position_known:
                continue
            if self.entry_position is None:
                self.entry_position = contact.position
            self.exit_position = contact.position
            if self.entry_position is not None:
                displacement = contact.position - self.entry_position
                if abs(displacement) >= .15 and not self.direction:
                    self.direction = 1 if displacement > 0 else -1
                previous = [c for c in [c for c in ordered if (c.start, c.id) < (contact.start, contact.id)]
                            if c.label and c.position_known and c.epoch == contact.epoch]
                if previous and self.direction and (contact.position - previous[-1].position) * self.direction < -.15:
                    contact.exclusion = "turn_detected"
                    self.finished_reason = "turn_detected"

    def _close_observation_waits(self):
        grouped = {s['source_id'] for g in self._ownership_groups for s in g['sources']}
        for c in self.active:
            if (c.confirmed or c.candidate_outcome != 'pending' or c.ownership_source_id in grouped
                    or c.observation_wait_since is None
                    or self.last_sample-c.observation_wait_since < self.OWNERSHIP_OBSERVATION_BUDGET_MS):
                continue
            c.observation_closed_sample = self.last_sample
            c.candidate_outcome = 'unresolved'
            self._censor_duration_start(c.start, c.edge_estimates.get('touch'))
            self._record_candidate(c, 'unresolved', 'observation_budget', self.last_sample)
        for p in self._narrow_candidates:
            if (p.get('observation_closed_sample') is None and p.get('observation_wait_since') is not None
                    and self.last_sample-p['observation_wait_since'] >= self.OWNERSHIP_OBSERVATION_BUDGET_MS):
                p['observation_closed_sample'] = self.last_sample
                self._censor_duration_start(p['start'])
                self._record_candidate(p, 'unresolved', 'observation_budget', self.last_sample)
                self._narrow_barriers.append((p['start'], p['start']+.001))
                self._identity_known = False

    def _at_exit(self):
        if not self.direction or self.entry_position is None or self.exit_position is None:
            return False
        low, high = self.positions[0], self.positions[-1]
        margin = min(.6, (high - low) * .4)
        if self.direction > 0:
            return self.entry_position <= low + margin and self.exit_position >= high - margin
        return self.entry_position >= high - margin and self.exit_position <= low + margin

    def _record_visual(self, frame, *, force=False):
        if self.origin is None or (not force and frame.sample_time_s - self._last_visual < .04):
            return
        self._last_visual = frame.sample_time_s
        self.timeline.append({
            "timestamp_s": frame.sample_time_s - self.origin,
            "sample_index": frame.sample_index,
            "contact_bits": list(frame.contact_bits),
            "positions_m": self.positions,
            "segment_ids": tuple(s.segment_id for s in self.device.layout.segments),
            "valid_bits": list(frame.valid_bits),
            "quality_flags": list(frame.quality_flags),
            "feet": [{"contact_id": c.id, "label": c.label,
                      "centroid_cm": (self._landing_positions.get(c.id,c.position)
                                      if c.exclusion else c.position) * 100,
                      "length_cm": None if c.exclusion else (self.positions[c.high] - self.positions[c.low]) * 100,
                      "side": 'unknown' if c.exclusion else c.side,
                      "shape_valid": not c.exclusion and c.position_known,
                      "status": "confirmed" if self._touch_events.get(c.id, {}).get('active') else "candidate"}
                     for c in self.active],
        })

    def _movement_end(self):
        end = self.last_occupied + .001 if self.last_occupied is not None else self.origin
        if (self.last_occupied is not None and any(c.end is not None and 'lift' in c.edge_estimates
                                                 and c.end >= self.last_occupied for c in self.contacts)):
            end = max(c.end for c in self.contacts if c.end is not None and c.end >= self.last_occupied)
        return end

    def _stop_intervals(self):
        confirmed = [c for c in self.contacts if c.confirmed and c.label]
        end = self._movement_end()
        stops = dict(self._preserved_stops)
        for i, c in enumerate(confirmed):
            nxt = confirmed[i + 1] if i + 1 < len(confirmed) else None
            until = nxt.start if nxt else end
            # Only a continuously observed stationary contact supports a stop claim.
            observed_end = c.end if c.end is not None else c.last + .001
            if c.end is None and c.last_reliable_sample is not None:
                observed_end = (c.last_reliable_sample + 1) / 1000
            until = min(until, observed_end) if until is not None else c.start
            if not c.exclusion and until - c.start >= self.config.stop_threshold_s:
                stops[c.start] = max(stops.get(c.start, until), until)
        return sorted(stops.items())

    def _centre(self, c):
        if not c.confirmed:
            return metric(reason='unconfirmed_contact')
        owned_group = any(g.get('restored_source_ids') and (ownership_record(g) or {}).get('owner_id') == c.id
                          for g in self._ownership_groups)
        if c.position_known and not c.exclusion and not owned_group:
            return metric(c.position)
        value, evidence = walking_centre_position(self, c)
        return {**metric(value, evidence['missing_reason']), 'evidence': evidence}

    def summary(self):
        confirmed = [c for c in self.contacts if c.confirmed]
        centres = {c.id: self._centre(c) for c in self.contacts}
        end = self._movement_end()
        stops = self._stop_intervals()
        release_evidence = {c.id: c.terminal_release_evidence if c.terminal_release_evidence.get('valid')
                            else group_release_evidence(self._ownership_groups, c.id) for c in self.contacts}
        def lift_valid(c):
            evidence = release_evidence[c.id]
            if evidence is not None:
                return evidence['missing_reason'] is None
            return c.confirmed and c.end is not None and not c.exclusion
        def valid(c):
            evidence = release_evidence[c.id]
            return (c.confirmed and c.touch_known and lift_valid(c)
                    and (evidence is None or evidence['occupancy_valid']))
        def touch_valid(c):
            return (c.confirmed and bool(c.label) and c.touch_known
                    and c.exclusion not in {'simultaneous_contacts', 'turn_detected'})
        def position_valid(c):
            return centres[c.id]['valid']
        grouped_sources = {s['source_id'] for g in self._ownership_groups for s in g['sources']}
        barriers = [(a / 1000, b / 1000) for a, b, _ in self._ownership_barriers()] + self._narrow_barriers + [
            (gap['start_sample'] / 1000, gap['end_sample'] / 1000)
            for c in self.contacts if c.ownership_source_id not in grouped_sources
            for gap in c.merged_interruptions if gap['reason'] == 'unresolved_fragment_join']
        def moving(start, end):
            return not any(start < b and end > a for a, b in stops + barriers)
        steps, strides, cycles = [], [], []
        # Only a fully closed non-step decision permits skipping a candidate.
        sequence = sorted((c for c in self.contacts if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}), key=lambda c: (c.start, c.id))
        for i, c in enumerate(sequence):
            if i:
                prev = sequence[i - 1]
                dt = c.start - prev.start
                if (touch_valid(prev) and touch_valid(c) and prev.epoch == c.epoch and prev.label != c.label
                        and dt > 0 and moving(prev.start, c.start)):
                    distance = abs(centres[c.id]['value'] - centres[prev.id]['value']) if all(position_valid(x) for x in (prev, c)) else None
                    steps.append({"from_id": prev.id, "to_id": c.id,
                                  "length_m": distance, "time_s": dt,
                                  "speed_m_s": distance / dt if distance is not None else None})
            if i < 2:
                continue
            a, b = sequence[i - 2:i]
            if not (all(touch_valid(x) for x in (a, b, c)) and a.epoch == b.epoch == c.epoch
                    and a.label == c.label != b.label and moving(a.start, c.start)):
                continue
            # Cycle time needs touch/identity evidence; support additionally
            # needs the intervening occupied intervals, not the endpoint's lift.
            relevant = [x for x in confirmed if x.start < c.start
                        and (x.end if x.end is not None else x.last + .001) > a.start]
            single = double = None
            support_ends = {x.id: release_evidence[x.id]['occupied_until_sample'] / 1000
                            if release_evidence[x.id] and release_evidence[x.id]['occupancy_valid'] else x.end
                            for x in relevant}
            if all((valid(x) or release_evidence[x.id] and release_evidence[x.id]['occupancy_valid'])
                   and x.epoch == a.epoch and (release_evidence[x.id] is not None or not x.has_unknown)
                   and (release_evidence[x.id] is not None or not any(a.start * 1000 < gap['end_sample'] and c.start * 1000 > gap['start_sample']
                               for gap in x.merged_interruptions)) for x in relevant):
                boundaries = sorted({a.start, c.start, *[max(a.start, x.start) for x in relevant],
                                     *[min(c.start, support_ends[x.id]) for x in relevant]})
                single = double = 0.0
                for left, right in zip(boundaries, boundaries[1:]):
                    midpoint = (left + right) / 2
                    count = sum(x.start <= midpoint < support_ends[x.id] for x in relevant)
                    if count > 2:
                        single = double = None
                        break
                    if count == 1:
                        single += right - left
                    elif count == 2:
                        double += right - left
            if all(position_valid(x) for x in (a, c)):
                strides.append(abs(centres[c.id]['value'] - centres[a.id]['value']))
            known_spans = [(x.start, support_ends[x.id]) for x in relevant
                           if release_evidence[x.id] and release_evidence[x.id]['occupancy_valid']]
            def covered(left,right):
                cursor = max(a.start,left)
                for lo,hi in sorted(known_spans):
                    if lo <= cursor < hi:
                        cursor = max(cursor,hi)
                return cursor >= min(c.start,right)
            unknown = [(left,right) for left,right in self._narrow_unknown if not covered(left,right)]
            unknown += self._narrow_barriers
            unknown += [(p['start'], p['last'] + .001) for p in self._narrow_candidates]
            unknown += [(x.start, x.end if x.end is not None else x.last + .001)
                        for x in sequence if not x.confirmed]
            if any(a.start < right and c.start > left for left, right in unknown):
                single = double = None
            cycles.append({"foot": a.label, "side": a.side if a.side == c.side else 'unknown', "epoch": a.epoch,
                           "start_s": a.start - self.origin, "end_s": c.start - self.origin,
                           "duration_s": c.start - a.start,
                           "single_support_s": single, "double_support_s": double})
        duration = max(0, end - self.origin) if end is not None and self.origin is not None else None
        if (self._duration_start_censored or self._duration_censored and (
                self._duration_clear_upper is None or end is None
                or end * 1000 + 1e-9 < self._duration_clear_upper)):
            duration = None
        speed = None
        if (len(confirmed) >= 2 and not self.issues and duration and self.direction
                and all(position_valid(c) for c in (confirmed[0], confirmed[-1]))):
            # Optical progression of landing positions, not centre-of-mass velocity.
            speed = abs(centres[confirmed[-1].id]['value'] - centres[confirmed[0].id]['value']) / duration
        contacts = [c.end - c.start for c in confirmed if valid(c)
                    and not any(c.start < b and c.end > a for a, b in stops)]
        spatial_steps = [s for s in steps if s['length_m'] is not None]
        avg = lambda values: sum(values) / len(values) if values else None
        summary = {"segment_count": len(self.device.layout.segments),
                "nominal_length_m": len(self.device.layout.segments),
                "duration_s": duration, "passage_speed_m_s": speed,
                "direction": self.direction, "valid_steps": len(steps), "valid_cycles": len(cycles),
                "event_publications": self.touch_events, "event_audit": deepcopy(self.event_audit),
                "landing_positions_m": {str(cid): position for cid,position in self._landing_positions.items()
                                        if self._touch_events[cid]['active']},
                "ownership_recoveries": [deepcopy(g["recovery"]) for g in self._ownership_groups if g.get("recovery")],
                "record_count": len(self.contacts), "confirmed_contacts": len(confirmed),
                "valid_touches": self.reliable_touch_count,
                "metric_policy": METRIC_POLICY,
                "valid_step_times": len(steps), "valid_step_lengths": len(spatial_steps),
                "valid_step_speeds": len(spatial_steps),
                "valid_cycle_times": len(cycles), "valid_stride_lengths": len(strides),
                "valid_support_cycles": sum(c['single_support_s'] is not None for c in cycles),
                "valid_contact_durations": len(contacts),
                "spatial_sources": {str(c.id): [list(island) for island in c.source_islands] for c in self.contacts},
                "candidate_decisions": [dict(row) for row in self._candidate_decisions]
                    + [self._candidate_row(p, 'unresolved' if p.get('observation_closed_sample') is not None else 'pending',
                        'observation_budget' if p.get('observation_closed_sample') is not None else 'awaiting_release_or_confirmation',
                        p.get('observation_closed_sample')) for p in self._narrow_candidates]
                    + [self._candidate_row(c, 'pending', 'awaiting_release_or_confirmation')
                       for c in self.active if not c.confirmed and c.candidate_outcome == 'pending'],
                "step_lengths_m": [s["length_m"] for s in spatial_steps],
                "stride_lengths_m": strides, "steps": steps, "cycles": cycles,
                "mean_step_m": avg([s["length_m"] for s in spatial_steps]),
                "mean_stride_m": avg(strides), "mean_contact_s": avg(contacts),
                "cadence_per_min": 60 * len(steps) / sum(s["time_s"] for s in steps) if steps else None,
                "walking_speed_m_s": sum(s["length_m"] for s in spatial_steps) / sum(s["time_s"] for s in spatial_steps) if spatial_steps else None,
                "single_support_s": avg([c["single_support_s"] for c in cycles if c["single_support_s"] is not None]),
                "double_support_s": avg([c["double_support_s"] for c in cycles if c["double_support_s"] is not None]),
                "stops": [{"start_s": a - self.origin, "end_s": b - self.origin} for a, b in stops],
                "issues": [{**issue, "time_s": issue["time_s"] - self.origin
                            if issue["time_s"] is not None and self.origin is not None else None}
                           for issue in self.issues],
                "contacts": [{**{k: v for k, v in vars(c).items()
                                 if k not in {"positions", "merged_interruptions", "has_unknown", "edge_estimates", "absent_samples", "release_start", "candidate_since", "last_reliable_sample", "isolated_clear", "clear_before_candidate", "source_islands", "valid_sample_intervals", "ownership_source_id", "ownership_unresolved_since", "terminal_release_evidence", "position_samples", "observation_wait_since", "observation_closed_sample"}},
                              **({'observation_wait_since': c.observation_wait_since, 'observation_closed_sample': c.observation_closed_sample}
                                 if c.observation_closed_sample is not None else {}),
                              "touch_sample": round(c.start * 1000) if c.confirmed and c.touch_known
                                  and 'touch' not in c.edge_estimates else None,
                              "lift_sample": round(c.end * 1000) if lift_valid(c) and 'lift' not in c.edge_estimates else None,
                              "confirmed_sample": round(c.confirmed_at * 1000) if c.confirmed_at is not None else None,
                              "merged_interruptions": [dict(item) for item in c.merged_interruptions],
                              "touch_s": metric(c.start - (self.origin or 0) if c.confirmed and c.touch_known else None),
                              "lift_s": metric(c.end - (self.origin or 0) if lift_valid(c) else None,
                                               release_evidence[c.id]['missing_reason'] if release_evidence[c.id] else None),
                              "contact_s": metric(c.end - c.start if valid(c) else None,
                                  'stop_interval' if any(c.start < b and (c.end or c.last + .001) > a for a,b in stops)
                                  else 'contact_continuity_unknown' if lift_valid(c) and not valid(c)
                                  else release_evidence[c.id]['missing_reason'] if release_evidence[c.id] else None),
                              "metric_evidence": {"lift": release_evidence[c.id] or {"basis": "observed_contact_boundary"}},
                              "centre_m": centres[c.id],
                              "position_m": centres[c.id]['value'] if position_valid(c) else c.position,
                              "start": c.start - (self.origin or 0),
                              "end": c.end - (self.origin or 0) if c.end is not None else None,
                              "last": c.last - (self.origin or 0),
                              "confirmed_at": c.confirmed_at - (self.origin or 0) if c.confirmed_at is not None else None,
                              "lift_confirmed_at": c.lift_confirmed_at - (self.origin or 0) if c.lift_confirmed_at is not None else None,
                              "exclusion": c.exclusion or ("pending_touch_order" if c.confirmed and not c.label
                                                            else "incomplete_contact" if c.end is None else None)}
                             for c in self.contacts],
                "excluded_contacts": sum(not valid(c) for c in self.contacts)}
        from engine.footfall_records import FOOTFALL_SCHEMA, footfall_records
        summary['footfall_schema_version'] = FOOTFALL_SCHEMA
        summary['footfalls'] = footfall_records(summary)
        summary['recognized_steps'] = len(summary['footfalls'])
        return summary

    def build_report(self, reason, export_frames=(), export_timestamps=()):
        self._close_ownership_groups(reason, self.last_sample)
        self._publication_closed = True
        self._commit_contacts()
        summary = self.summary()
        steps_cm = tuple(x * 100 for x in summary["step_lengths_m"])
        velocities = tuple(x["speed_m_s"] * 100 for x in summary["steps"] if x['speed_m_s'] is not None)
        return GaitTestReport(
            touch_count=summary['valid_touches'],
            lift_count=sum(c["lift_s"]["valid"] for c in summary["contacts"]),
            stride_lengths=steps_cm, velocities=velocities,
            avg_stride=summary["mean_step_m"] * 100 if steps_cm else None,
            max_stride=max(steps_cm) if steps_cm else None,
            avg_velocity=summary["walking_speed_m_s"] * 100 if velocities else None,
            max_velocity=max(velocities) if velocities else None,
            avg_single_support=summary["single_support_s"], avg_double_support=summary["double_support_s"],
            finish_reason=reason, export_frames=export_frames, export_timestamps=export_timestamps,
            visual_timeline=tuple(self.timeline), walking_summary=summary,
            report_config_snapshot={**self.config.to_dict(), "device": self.device.snapshot(),
                                    "algorithm": "overground_walking_v1.15",
                                    "metric_policy": METRIC_POLICY,
                                    "fragment_association": "valid_previous_blocked_overlap_per_island",
                                    "source_uncertainty_recovery": "all_sources_attributed_to_established_owner",
                                    "footprint_publication": "active_touch_independent_of_current_shape",
                                    "narrow_candidate_policy": "local_candidate_evidence_before_identity",
                                    "candidate_exclusion_policy": "closed_isolated_single_beam_single_sample",
                                    "immature_coalescence_policy": "local_tracking_with_unresolved_identity"},
        )
