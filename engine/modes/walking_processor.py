"""Single-pass overground walking on calibrated beam coordinates.

Beam interruption is an optical contact proxy, not force-plate contact. Ambiguous
merges and acquisition gaps break continuity. Bounded local unknowns carry evidence.
"""
from dataclasses import dataclass, field
from statistics import median

from config.test_report import GaitTestReport
from config.walking_config import WalkingConfig
from hardware.sensor_frame import blocked_indices
from hardware.walking_preflight import PreparedDevice


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

    @property
    def position(self):
        return median(self.positions)


class WalkingProcessor:
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

    def break_continuity(self, code, frame_index=None):
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

    def _clusters(self, bits):
        if b'\x01' not in bits:
            return []
        groups = []
        for i in sorted(blocked_indices(bits)):
            if groups and self.positions[i] - self.positions[groups[-1][-1]] <= .04:
                groups[-1].append(i)
            else:
                groups.append([i])
        # Keep edge fragments so incomplete entry/exit contacts cannot look complete.
        return [(g[0], g[-1]) for g in groups]

    def _associate_inner_fragments(self, groups):
        # A heel/forefoot gap can split one already observed footprint. Join
        # only fragments uniquely contained in its preceding spatial envelope
        # plus a bounded margin for stance roll. An inner island must still
        # anchor the group to the preceding footprint.
        owners, anchored = {}, set()
        for index, (low, high) in enumerate(groups):
            candidates = [c for c in self.active
                          if self.positions[low] <= self.positions[c.high] + .035
                          and self.positions[high] >= self.positions[c.low] - .035]
            if len(candidates) != 1:
                continue
            contact = candidates[0]
            if (self.positions[low] >= self.positions[contact.low] - .035
                    and self.positions[high] <= self.positions[contact.high] + .035):
                owners.setdefault(contact.id, []).append(index)
                if self.positions[contact.low] <= self.positions[low] and self.positions[high] <= self.positions[contact.high]:
                    anchored.add(contact.id)
        merged, consumed = {}, set()
        for owner, indices in owners.items():
            if len(indices) > 1 and owner in anchored:
                merged[indices[0]] = (groups[indices[0]][0], groups[indices[-1]][1])
                consumed.update(indices[1:])
        return [merged.get(index, group) for index, group in enumerate(groups)
                if index not in consumed]

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
        row.update(outcome=outcome, reason=reason, closed_sample=closed_sample)
        row['isolated_clear_evidence'] = clear
        if owner_id is not None:
            row['owner_id'] = owner_id
        return row

    def _record_candidate(self, candidate, outcome, reason, closed_sample=None, owner_id=None):
        self._candidate_decisions.append(self._candidate_row(candidate, outcome, reason, closed_sample, owner_id))

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
            candidates = [c for c in self.active if low <= c.high + 3 and high >= c.low - 3]
            pair = self._immature_pair(candidates, low, high, sample)
            if pair is None:
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
                if contact.exclusion != 'masked_contact_boundary':
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
        # Known bad beams censor their neighbouring footprint, not a remote
        # foot's observable touch. Keep tracking the affected owner so its
        # later visible fragment cannot be counted as another landing.
        if observation is not None:
            groups = observation.associate_fragments(groups, self.active)
        else:
            groups = self._associate_inner_fragments(groups)
            self._coalesce_immature_contacts(groups, frame.sample_index)
        seeds, candidate_ambiguity = {}, False
        if observation is None:
            groups, seeds, candidate_ambiguity = self._defer_narrow_candidates(groups, frame, affected)
        matches = []
        used = set()
        ambiguous = candidate_ambiguity or len(groups) > 2
        for low, high in groups:
            centre = (self.positions[low] + self.positions[high]) / 2
            candidates = [c for c in self.active
                          if low <= c.high + 3 and high >= c.low - 3
                          and abs((self.positions[c.low] + self.positions[c.high]) / 2 - centre) <= .18]
            if len(candidates) > 1 or (candidates and candidates[0].id in used):
                ambiguous = True
            if self.positions[high] - self.positions[low] > .45:
                ambiguous = True
            contact = candidates[0] if len(candidates) == 1 else None
            if contact:
                used.add(contact.id)
            matches.append((low, high, centre, contact))
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
            if contact is None:
                contact = Contact(len(self.contacts), self.epoch, "", "unknown", sample_time,
                                  sample_time, low, high, [centre])
                contact.clear_before_candidate = self.clear_since
                seed = seeds.get((low, high))
                if seed:
                    contact.start = seed['start']
                    contact.observed_samples = seed['samples'] - 1
                    contact.positions = list(seed.get('positions', [seed['centre']]))
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
                    if observation.affected(low, high, observation.recovery_segments):
                        contact.exclusion = 'unknown_touch_after_gap'
                        contact.touch_known = False
                self.contacts.append(contact)
                self.active.append(contact)
                new_contacts.append(contact)
            elif sample_time - contact.last > .001 + 1e-9 and contact.release_start is not None:
                contact.merged_interruptions.append({
                    "start_sample": round(contact.last * 1000) + 1,
                    "end_sample": frame.sample_index, "reason": "release_debounce",
                })
            contact.last = sample_time
            if any(low <= right and high >= left for left, right in affected):
                contact.exclusion = 'masked_contact_boundary'
                contact.touch_known &= contact.confirmed
                contact.position_known = False
            reliable = observation is None or observation.reliable(low, high)
            contact.observed_samples += int(reliable and contact.exclusion != 'local_unknown_timeout')
            if reliable:
                contact.last_reliable_sample = frame.sample_index
            if reliable:
                contact.absent_samples = 0
                contact.release_start = None
                contact.candidate_since = None
            contact.low, contact.high = low, high
            if reliable:
                contact.peak_width_m = max(contact.peak_width_m, self.positions[high] - self.positions[low])
            if observation is not None:
                contact.has_unknown |= observation.affected(low, high, observation.unknown_segments) or bool(observation.edge(low, high, 1))
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
                    and contact.observed_samples >= self.config.confirmation_ms
                    and sample_time - contact.start + .001 + 1e-9 >= self.config.min_contact_time / 1000):
                contact.confirmed = True
                contact.candidate_outcome = 'confirmed_contact'
                contact.confirmed_at = sample_time

        matched = {c.id for _, _, _, c in matches if c is not None}
        matched.update(c.id for c in new_contacts)
        for contact in list(self.active):
            if contact.id in matched:
                continue
            if contact.exclusion == 'local_unknown_timeout':
                if observation.reliable(contact.low, contact.high):
                    self.active.remove(contact)
                continue
            reliable = observation is None or observation.release_reliable(
                contact.low, contact.high, 3 * self.device.layout.segments[contact.high // 96].pitch_m)
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
                c.exclusion = c.exclusion or "simultaneous_contacts"
                c.touch_known = False
                self._censor_duration_start(c.start, c.edge_estimates.get('touch'))
            self._identity_known = False
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
        self._narrow_barriers.extend((p['start'], p['last'] + .001) for p in unresolved)
        if unresolved:
            self._identity_known = False
            for c in self.contacts:
                if any(c.start >= p['start'] for p in unresolved):
                    c.side = 'unknown'
        owners = []
        for low, high in groups:
            centre = (self.positions[low] + self.positions[high]) / 2
            owners.append([c for c in self.active if low <= c.high + 3 and high >= c.low - 3
                           and abs((self.positions[c.low] + self.positions[c.high]) / 2 - centre) <= .18])
        anchored = any(len(cs) == 1 and cs[0].confirmed
                       and cs[0].exclusion in {None, 'simultaneous_contacts', 'unresolved_coalescence'} for cs in owners)
        independent_wide = bool(pending) and any(not cs and self.positions[high] - self.positions[low] >= .08
                           and not any(low <= p['high'] + 3 and high >= p['low'] - 3 for p in pending)
                           for (low, high), cs in zip(groups, owners))
        if independent_wide:
            # Do not let a later independent foot overtake an earlier unresolved
            # touch. Restore normal candidate/ambiguity handling for this frame.
            anchored = False
        kept, seeds, touched, ambiguous = [], {}, set(), False
        for (low, high), cs in zip(groups, owners):
            candidates = [p for p in pending if low <= p['high'] + 3 and high >= p['low'] - 3]
            if cs:
                kept.append((low, high))
                immature = len(cs) == 1 and not cs[0].confirmed and candidates
                if immature:
                    pair = self._immature_pair([cs[0], *candidates], low, high, frame.sample_index)
                    if pair is None or not isinstance(pair[0], Contact):
                        ambiguous = True
                        continue
                    contact = cs[0]
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
                    self._record_candidate(p, 'associated_fragment',
                                           'immature_islands_coalesced' if immature else 'joined_existing_footprint',
                                           frame.sample_index, cs[0].id if len(cs) == 1 else None)
                if any(p.get('masked_contact') for p in candidates):
                    for c in cs:
                        c.exclusion = 'masked_contact_boundary'
                        c.touch_known &= c.confirmed
                        c.position_known = False
                touched.update(id(p) for p in candidates)
                continue
            if len(candidates) > 1:
                pair = self._immature_pair(candidates, low, high, frame.sample_index)
                if pair is None:
                    kept.append((low, high))
                    ambiguous = True
                    continue
                a, b = pair
                self._record_candidate(b, 'associated_fragment', 'immature_islands_coalesced', frame.sample_index)
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
                     'merged_interruptions': []}
                p['isolated_gate'] = isolated_gate
                if isolated_gate:
                    p['positions'] = [p['centre']]
                pending.append(p)
            if p is None:
                kept.append((low, high))
                continue
            if p['samples'] and frame.sample_index > p['last_sample'] + 1:
                p['merged_interruptions'].append({'start_sample': p['last_sample'] + 1,
                                                  'end_sample': frame.sample_index, 'reason': 'release_debounce'})
            p.update(last=t, last_sample=frame.sample_index, low=low, high=high, samples=p['samples'] + 1)
            p['peak_width_m'] = max(p['peak_width_m'], width)
            p['masked_contact'] = p.get('masked_contact', False) or any(
                low <= right and high >= left for left, right in affected)
            if (not anchored and (not p.get('isolated_gate') or independent_wide)
                    or width >= .08 or low == 0 or high == len(self.positions)-1
                    or t - p['start'] + .001 + 1e-9 >=
                    max(self.config.min_contact_time, self.config.confirmation_ms) / 1000):
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
        # Creation order is touch order. An unresolved earlier candidate blocks
        # identity and direction publication, even if a later foot confirms first.
        while self._commit_cursor < len(self.contacts):
            contact = self.contacts[self._commit_cursor]
            if any(p['start'] < contact.start for p in self._narrow_candidates):
                break
            if not contact.confirmed and contact.end is None and not contact.exclusion:
                break
            self._commit_cursor += 1
            if not contact.confirmed:
                continue
            self._last_label = "A" if self._last_label == "B" else "B"
            contact.label = self._last_label
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
                previous = [c for c in self.contacts[:contact.id]
                            if c.label and c.position_known and c.epoch == contact.epoch]
                if previous and self.direction and (contact.position - previous[-1].position) * self.direction < -.15:
                    contact.exclusion = "turn_detected"
                    self.finished_reason = "turn_detected"

    def _at_exit(self):
        if not self.direction or self.entry_position is None or self.exit_position is None:
            return False
        low, high = self.positions[0], self.positions[-1]
        margin = min(.6, (high - low) * .4)
        if self.direction > 0:
            return self.entry_position <= low + margin and self.exit_position >= high - margin
        return self.entry_position >= high - margin and self.exit_position <= low + margin

    def _record_visual(self, frame):
        if self.origin is None or frame.sample_time_s - self._last_visual < .04:
            return
        self._last_visual = frame.sample_time_s
        self.timeline.append({
            "timestamp_s": frame.sample_time_s - self.origin,
            "contact_bits": list(frame.contact_bits),
            "positions_m": self.positions,
            "segment_ids": tuple(s.segment_id for s in self.device.layout.segments),
            "valid_bits": list(frame.valid_bits),
            "quality_flags": list(frame.quality_flags),
            "feet": [{"contact_id": c.id, "side": c.side, "label": c.label,
                      "centroid_cm": c.position * 100,
                      "length_cm": (self.positions[c.high] - self.positions[c.low]) * 100,
                      "status": "confirmed" if c.confirmed and not c.exclusion else "candidate"}
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

    def summary(self):
        confirmed = [c for c in self.contacts if c.confirmed]
        end = self._movement_end()
        stops = self._stop_intervals()
        def valid(c):
            return c.confirmed and c.touch_known and c.end is not None and not c.exclusion
        def touch_valid(c):
            return (c.confirmed and bool(c.label) and c.touch_known
                    and c.exclusion not in {'simultaneous_contacts', 'turn_detected'})
        def position_valid(c):
            return c.position_known and not c.exclusion
        def moving(start, end):
            return not any(start < b and end > a for a, b in stops + self._narrow_barriers)
        steps, strides, cycles = [], [], []
        # Only a fully closed non-step decision permits skipping a candidate.
        sequence = [c for c in self.contacts if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}]
        for i, c in enumerate(sequence):
            if i:
                prev = sequence[i - 1]
                dt = c.start - prev.start
                if (touch_valid(prev) and touch_valid(c) and prev.epoch == c.epoch and prev.label != c.label
                        and dt > 0 and moving(prev.start, c.start)):
                    distance = abs(c.position - prev.position) if all(position_valid(x) for x in (prev, c)) else None
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
            if all(valid(x) and x.epoch == a.epoch and not x.has_unknown
                   and not any(a.start * 1000 < gap['end_sample'] and c.start * 1000 > gap['start_sample']
                               for gap in x.merged_interruptions) for x in relevant):
                boundaries = sorted({a.start, c.start, *[max(a.start, x.start) for x in relevant],
                                     *[min(c.start, x.end) for x in relevant]})
                single = double = 0.0
                for left, right in zip(boundaries, boundaries[1:]):
                    midpoint = (left + right) / 2
                    count = sum(x.start <= midpoint < x.end for x in relevant)
                    if count == 1:
                        single += right - left
                    elif count == 2:
                        double += right - left
            if all(position_valid(x) for x in (a, c)):
                strides.append(abs(c.position - a.position))
            unknown = self._narrow_unknown + [(p['start'], p['last'] + .001)
                                              for p in self._narrow_candidates]
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
                and valid(confirmed[0]) and valid(confirmed[-1])):
            # Optical progression of landing positions, not centre-of-mass velocity.
            speed = abs(confirmed[-1].position - confirmed[0].position) / duration
        contacts = [c.end - c.start for c in confirmed if valid(c)
                    and not any(c.start < b and c.end > a for a, b in stops)]
        spatial_steps = [s for s in steps if s['length_m'] is not None]
        avg = lambda values: sum(values) / len(values) if values else None
        return {"segment_count": len(self.device.layout.segments),
                "nominal_length_m": len(self.device.layout.segments),
                "duration_s": duration, "passage_speed_m_s": speed,
                "direction": self.direction, "valid_steps": len(steps), "valid_cycles": len(cycles),
                "record_count": len(self.contacts), "confirmed_contacts": len(confirmed),
                "valid_touches": sum(c.confirmed and c.touch_known for c in self.contacts),
                "valid_step_times": len(steps), "valid_step_lengths": len(spatial_steps),
                "valid_cycle_times": len(cycles), "valid_stride_lengths": len(strides),
                "valid_support_cycles": sum(c['single_support_s'] is not None for c in cycles),
                "valid_contact_durations": len(contacts),
                "candidate_decisions": [dict(row) for row in self._candidate_decisions]
                    + [self._candidate_row(p, 'pending', 'awaiting_release_or_confirmation') for p in self._narrow_candidates]
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
                                 if k not in {"positions", "merged_interruptions", "has_unknown", "edge_estimates", "absent_samples", "release_start", "candidate_since", "last_reliable_sample", "isolated_clear", "clear_before_candidate"}},
                              "touch_sample": round(c.start * 1000) if c.confirmed and c.touch_known
                                  and 'touch' not in c.edge_estimates else None,
                              "lift_sample": round(c.end * 1000) if valid(c) and 'lift' not in c.edge_estimates else None,
                              "confirmed_sample": round(c.confirmed_at * 1000) if c.confirmed_at is not None else None,
                              "merged_interruptions": [dict(item) for item in c.merged_interruptions],
                              "position_m": c.position,
                              "start": c.start - (self.origin or 0),
                              "end": c.end - (self.origin or 0) if c.end is not None else None,
                              "last": c.last - (self.origin or 0),
                              "confirmed_at": c.confirmed_at - (self.origin or 0) if c.confirmed_at is not None else None,
                              "lift_confirmed_at": c.lift_confirmed_at - (self.origin or 0) if c.lift_confirmed_at is not None else None,
                              "exclusion": c.exclusion or ("pending_touch_order" if c.confirmed and not c.label
                                                            else "incomplete_contact" if c.end is None else None)}
                             for c in self.contacts],
                "excluded_contacts": sum(not valid(c) for c in self.contacts)}

    def build_report(self, reason, export_frames=(), export_timestamps=()):
        summary = self.summary()
        steps_cm = tuple(x * 100 for x in summary["step_lengths_m"])
        velocities = tuple(x["speed_m_s"] * 100 for x in summary["steps"] if x['speed_m_s'] is not None)
        return GaitTestReport(
            touch_count=summary['valid_touches'],
            lift_count=sum(c.confirmed and c.touch_known and c.end is not None and not c.exclusion
                           for c in self.contacts),
            stride_lengths=steps_cm, velocities=velocities,
            avg_stride=summary["mean_step_m"] * 100 if steps_cm else None,
            max_stride=max(steps_cm) if steps_cm else None,
            avg_velocity=summary["walking_speed_m_s"] * 100 if velocities else None,
            max_velocity=max(velocities) if velocities else None,
            avg_single_support=summary["single_support_s"], avg_double_support=summary["double_support_s"],
            finish_reason=reason, export_frames=export_frames, export_timestamps=export_timestamps,
            visual_timeline=tuple(self.timeline), walking_summary=summary,
            report_config_snapshot={**self.config.to_dict(), "device": self.device.snapshot(),
                                    "algorithm": "overground_walking_v1.10",
                                    "metric_policy": "independent_touch_position_support_dependencies",
                                    "fragment_association": "unique_existing_envelope_with_match_margin",
                                    "narrow_candidate_policy": "local_candidate_evidence_before_identity",
                                    "candidate_exclusion_policy": "closed_isolated_single_beam_single_sample",
                                    "immature_coalescence_policy": "local_tracking_with_unresolved_identity"},
        )
