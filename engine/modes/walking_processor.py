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
        self._ambiguous_now = False
        self._last_visual = -1.0
        self.timeline = []
        self._preserved_stops = []
        self._duration_censored = False
        self._duration_clear_upper = None

    def break_continuity(self, code, frame_index=None):
        self._preserved_stops = self._stop_intervals()
        t = self.last_time
        self.issues.append({"code": code, "time_s": t, "frame_index": frame_index})
        if self.origin is not None and t is not None:
            self.timeline.append({"timestamp_s": t - self.origin + .001, "positions_m": self.positions,
                                  "contact_bits": [0] * len(self.positions),
                                  "valid_bits": [0] * len(self.positions), "feet": [], "quality_flags": [code]})
        for contact in self.active:
            contact.exclusion = code
        for contact in self.contacts[self._commit_cursor:]:
            contact.exclusion = contact.exclusion or code
        self._commit_cursor = len(self.contacts)
        self.active.clear()
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
        if masked_contact:
            if not self._masked_contact_uncertain:
                self.break_continuity("masked_contact_boundary", frame.frame_index)
            self._masked_contact_uncertain = True
            return
        self._masked_contact_uncertain = False
        if observation is not None:
            if observation.unresolved_segments:
                self._duration_censored = True
                self._duration_clear_upper = None
            if (self._duration_censored and self._duration_clear_upper is None
                    and b'\x01' not in frame.contact_bits and b'\x00' not in frame.valid_bits):
                self._duration_clear_upper = frame.sample_index
            for contact in list(self.active):
                if observation.affected(contact.low, contact.high):
                    self._preserved_stops = self._stop_intervals()
                    contact.exclusion = 'local_unknown_timeout'
                    self.active.remove(contact)
                    self._identity_known = False
            for contact in list(self.active):
                if (contact.exclusion != 'local_unknown_timeout' and not contact.confirmed and contact.has_unknown
                        and frame.sample_index - contact.start * 1000 >=
                        max(self.config.min_contact_time, self.config.confirmation_ms) + 10):
                    contact.exclusion = 'local_unknown_timeout'
                    self._identity_known = False
                elif (contact.exclusion != 'local_unknown_timeout' and contact.candidate_since is not None
                      and frame.sample_index - contact.candidate_since >= self.config.release_ms + 10):
                    self._preserved_stops = self._stop_intervals()
                    contact.exclusion = 'local_unknown_timeout'
                    self._identity_known = False
        # Expire absence before association, including a return exactly at the
        # release threshold. The edge remains the first absent device sample.
        for contact in list(self.active):
            absent_start = contact.release_start if contact.release_start is not None else contact.last + .001
            released = (sample_time > absent_start + 1e-9
                        and sample_time - absent_start + 1e-9 >= self.config.release_ms / 1000)
            if observation is not None:
                released = (contact.absent_samples >= self.config.release_ms
                            and observation.release_reliable(contact.low, contact.high,
                                                            3 * self.device.layout.segments[contact.high // 96].pitch_m))
            if released:
                contact.end = absent_start
                contact.lift_confirmed_at = sample_time
                if (not contact.confirmed
                        or contact.end - contact.start + 1e-9 < self.config.min_contact_time / 1000):
                    contact.exclusion = contact.exclusion or "short_contact"
                    self._identity_known = False
                    for later in self.contacts[contact.id + 1:]:
                        later.side = "unknown"
                self.active.remove(contact)
        groups = self._clusters(frame.contact_bits)
        if observation is not None:
            groups = observation.associate_fragments(groups, self.active)
        else:
            groups = self._associate_inner_fragments(groups)
        matches = []
        used = set()
        ambiguous = len(groups) > 2
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
                if self._recovering:
                    contact.exclusion = "unknown_touch_after_gap"
                if observation is not None:
                    edge = observation.edge(low, high, 1)
                    if edge:
                        contact.start = edge.sample / 1000
                        contact.edge_estimates['touch'] = [edge.left_sample, edge.right_sample]
                    if observation.affected(low, high, observation.recovery_segments):
                        contact.exclusion = 'unknown_touch_after_gap'
                self.contacts.append(contact)
                self.active.append(contact)
                new_contacts.append(contact)
            elif sample_time - contact.last > .001 + 1e-9 and contact.release_start is not None:
                contact.merged_interruptions.append({
                    "start_sample": round(contact.last * 1000) + 1,
                    "end_sample": frame.sample_index, "reason": "release_debounce",
                })
            contact.last = sample_time
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
            wide_enough = contact.peak_width_m >= .08 or contact.exclusion == "boundary_contact"
            if (contact.exclusion != 'local_unknown_timeout' and not contact.confirmed and wide_enough
                    and contact.observed_samples >= self.config.confirmation_ms
                    and sample_time - contact.start + .001 + 1e-9 >= self.config.min_contact_time / 1000):
                contact.confirmed = True
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
            self._identity_known = False
        self._commit_contacts()
        # Existing footprints immediately after a gap have unknown touch times.
        # Later new contacts can be measured, with a new A/B identity epoch.
        self._recovering = False
        if b'\x01' in frame.contact_bits:
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

    def _commit_contacts(self):
        # Creation order is touch order. An unresolved earlier candidate blocks
        # identity and direction publication, even if a later foot confirms first.
        while self._commit_cursor < len(self.contacts):
            contact = self.contacts[self._commit_cursor]
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
                self.entry_position = contact.position
            self.exit_position = contact.position
            if self.entry_position is not None:
                displacement = contact.position - self.entry_position
                if abs(displacement) >= .15 and not self.direction:
                    self.direction = 1 if displacement > 0 else -1
                previous = [c for c in self.contacts[:contact.id] if c.label and c.epoch == contact.epoch]
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
            return c.confirmed and bool(c.label) and c.end is not None and not c.exclusion
        def moving(start, end):
            return not any(start < b and end > a for a, b in stops)
        steps, strides, cycles = [], [], []
        # Candidates remain in sequence: a rejected contact is a barrier, not a missing row.
        for i, c in enumerate(self.contacts):
            if i:
                prev = self.contacts[i - 1]
                dt = c.start - prev.start
                if (valid(prev) and valid(c) and prev.epoch == c.epoch and prev.label != c.label
                        and dt > 0 and moving(prev.start, c.start)):
                    distance = abs(c.position - prev.position)
                    steps.append({"from_id": prev.id, "to_id": c.id,
                                  "length_m": distance, "time_s": dt, "speed_m_s": distance / dt})
            if i < 2:
                continue
            a, b = self.contacts[i - 2:i]
            if not (all(valid(x) for x in (a, b, c)) and a.epoch == b.epoch == c.epoch
                    and a.label == c.label != b.label and moving(a.start, c.start)):
                continue
            # All overlapping contacts must also have known boundaries and identity.
            relevant = [x for x in confirmed if x.start < c.start
                        and (x.end if x.end is not None else x.last + .001) > a.start]
            if any(not valid(x) or x.epoch != a.epoch for x in relevant):
                continue
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
            strides.append(abs(c.position - a.position))
            cycles.append({"foot": a.label, "side": a.side, "epoch": a.epoch,
                           "start_s": a.start - self.origin, "end_s": c.start - self.origin,
                           "duration_s": c.start - a.start,
                           "single_support_s": single, "double_support_s": double})
        duration = max(0, end - self.origin) if end is not None and self.origin is not None else None
        if (self._duration_censored and (self._duration_clear_upper is None
                                        or end is None or end * 1000 + 1e-9 < self._duration_clear_upper)):
            duration = None
        speed = None
        if (len(confirmed) >= 2 and not self.issues and duration and self.direction
                and valid(confirmed[0]) and valid(confirmed[-1])):
            # Optical progression of landing positions, not centre-of-mass velocity.
            speed = abs(confirmed[-1].position - confirmed[0].position) / duration
        contacts = [c.end - c.start for c in confirmed if valid(c) and moving(c.start, c.end)]
        avg = lambda values: sum(values) / len(values) if values else None
        return {"segment_count": len(self.device.layout.segments),
                "nominal_length_m": len(self.device.layout.segments),
                "duration_s": duration, "passage_speed_m_s": speed,
                "direction": self.direction, "valid_steps": len(steps), "valid_cycles": len(cycles),
                "step_lengths_m": [s["length_m"] for s in steps],
                "stride_lengths_m": strides, "steps": steps, "cycles": cycles,
                "mean_step_m": avg([s["length_m"] for s in steps]),
                "mean_stride_m": avg(strides), "mean_contact_s": avg(contacts),
                "cadence_per_min": 60 * len(steps) / sum(s["time_s"] for s in steps) if steps else None,
                "walking_speed_m_s": sum(s["length_m"] for s in steps) / sum(s["time_s"] for s in steps) if steps else None,
                "single_support_s": avg([c["single_support_s"] for c in cycles]),
                "double_support_s": avg([c["double_support_s"] for c in cycles]),
                "stops": [{"start_s": a - self.origin, "end_s": b - self.origin} for a, b in stops],
                "issues": [{**issue, "time_s": issue["time_s"] - self.origin
                            if issue["time_s"] is not None and self.origin is not None else None}
                           for issue in self.issues],
                "contacts": [{**{k: v for k, v in vars(c).items()
                                 if k not in {"positions", "merged_interruptions", "has_unknown", "edge_estimates", "absent_samples", "release_start", "candidate_since", "last_reliable_sample"}},
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
        velocities = tuple(x["speed_m_s"] * 100 for x in summary["steps"])
        return GaitTestReport(
            touch_count=sum(c.confirmed for c in self.contacts),
            lift_count=sum(c.confirmed and c.end is not None for c in self.contacts),
            stride_lengths=steps_cm, velocities=velocities,
            avg_stride=summary["mean_step_m"] * 100 if steps_cm else None,
            max_stride=max(steps_cm) if steps_cm else None,
            avg_velocity=summary["walking_speed_m_s"] * 100 if velocities else None,
            max_velocity=max(velocities) if velocities else None,
            avg_single_support=summary["single_support_s"], avg_double_support=summary["double_support_s"],
            finish_reason=reason, export_frames=export_frames, export_timestamps=export_timestamps,
            visual_timeline=tuple(self.timeline), walking_summary=summary,
            report_config_snapshot={**self.config.to_dict(), "device": self.device.snapshot(),
                                    "algorithm": "overground_walking_v1.4",
                                    "fragment_association": "unique_existing_envelope_with_match_margin"},
        )
