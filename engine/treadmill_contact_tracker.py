"""Sample-based treadmill optical events. See docs/treadmill_event_evidence.md.

GaitR N means N+1 consecutive interrupted beams (OptoGait manual 5.1.6).
Confirmation and association policies below are Iron_Jump policies, not a
reconstruction of Microgate's proprietary detector.
"""

from dataclasses import dataclass

from engine.contact_tracker import ContactState, GaitStepEvent
from engine.spatial_clusterer import SPACING_CM, Cluster


@dataclass
class OpticalContact(ContactState):
    side: str = "unknown"
    peak_length_cm: float = 0.0
    out_time: float | None = None
    out_hold_s: float = .010
    touch_queued: bool = False


class TreadmillContactTracker:
    def __init__(self, config):
        self.config = config
        self.reset()

    def reset(self):
        self.active_contacts = {}
        self.touch_count = self.lift_count = 0
        self._next_id = 1
        self._pending = []
        self._last_label = None
        self._side_known = self.config.starting_foot_override is not None
        self._startup = True
        self._recovering = False
        self.boundary_reason = None
        self.rejected_contacts = []

    @property
    def foot_contact_queue(self):
        return [c.contact_id for c in self.active_contacts.values()
                if c.status == "confirmed" or c.is_initial_baseline]

    @property
    def observation_unknown(self):
        return self._recovering or self._startup

    @property
    def pending_evidence(self):
        return {
            "contacts": [{"contact_id": c.contact_id, "touch_time_s": c.touch_time,
                          "out_time_s": c.out_time, "baseline": c.is_initial_baseline}
                         for c in self.active_contacts.values()],
            "events": [{"contact_id": e.contact.contact_id, "kind": e.kind,
                        "time_s": event_time(e), "confirmed_time_s": e.confirmed_time_s}
                       for e in self._pending],
        }

    def break_continuity(self):
        self.rejected_contacts.extend({**event, "reason": "pending_event_interrupted"}
                                      for event in self.pending_evidence["events"])
        for c in self.active_contacts.values():
            self.rejected_contacts.append({
                "contact_id": c.contact_id, "touch_time_s": c.touch_time,
                "last_observed_time_s": c.last_seen_time, "reason": "continuity_interrupted",
            })
        self.active_contacts.clear()
        self._pending.clear()
        self._last_label = None
        self._side_known = False
        self._startup = True

    def _new_contact(self, cluster, time_s, baseline=False):
        c = OpticalContact(
            contact_id=self._next_id, first_seen_time=time_s,
            last_seen_time=time_s, is_initial_baseline=baseline,
        )
        self._next_id += 1
        self.active_contacts[c.contact_id] = c
        self._observe(c, cluster, time_s)
        return c

    def _observe(self, c, cluster, time_s):
        c.last_seen_time = time_s
        c.latest_centroid = cluster.centroid_cm
        c.latest_cluster_length = cluster.length * SPACING_CM
        c.latest_cluster_start_cm = cluster.start * SPACING_CM
        c.latest_cluster_end_cm = cluster.end * SPACING_CM
        c.peak_length_cm = max(c.peak_length_cm, c.latest_cluster_length)
        threshold = (self.config.filter_gaitr_out if c.touch_time is not None
                     or c.is_initial_baseline else self.config.filter_gaitr_in)
        if cluster.length <= threshold:
            if c.out_time is None:
                c.out_time = time_s
                c.out_hold_s = .010
            return
        c.out_time = None
        if c.touch_time is None and not c.is_initial_baseline:
            c.touch_time = time_s
            c.centroid_at_touch = cluster.centroid_cm
            c.cluster_length_at_touch = c.latest_cluster_length
        c.seen_count += 1

    def _assign_label(self, c):
        c.foot_label = "B" if self._last_label == "A" else "A"
        self._last_label = c.foot_label
        c.label_confidence = .7  # Alternation assumption, never anatomical evidence.
        if self._side_known:
            first = self.config.starting_foot_override
            c.side = first if c.foot_label == "A" else ("right" if first == "left" else "left")

    def process_frame(self, time_s: float, clusters: list[Cluster]):
        self.boundary_reason = None
        if self._recovering:
            # Clear space or two separated footprints can restart anonymous
            # observations, but neither restores anatomical identity.
            if not clusters:
                self._recovering = False
                self._startup = False
                return []
            if len(clusters) != 2 or any(c.length * SPACING_CM < self.config.min_foot_length for c in clusters):
                return []
            self._recovering = False
        if self._startup:
            self._startup = False
            initial = [self._new_contact(c, time_s, True) for c in clusters]
            if len(initial) == 2 and self._side_known:
                choose_front = max if self.config.direction == "Interface side" else min
                front = choose_front(initial, key=lambda c: c.latest_centroid)
                self._assign_label(front)
                self._assign_label(next(c for c in initial if c is not front))
                self._last_label = "A"  # Front foot is the latest initial contact.
            return [GaitStepEvent("baseline", c, time_s) for c in initial]

        # Associate actual observations only. Overlap handles heel/toe rolling;
        # a many-to-one or one-to-many overlap is explicitly ambiguous.
        hold = max(.010, self.config.min_flight_time / 1000 if not clusters else .010)
        for c in list(self.active_contacts.values()):
            if c.out_time is not None and time_s - c.out_time + 1e-9 >= c.out_hold_s:
                self._finish_contact(c, time_s)
        contacts = list(self.active_contacts.values())
        overlaps = [(c, i) for c in contacts for i, cluster in enumerate(clusters)
                    if cluster.start * SPACING_CM <= c.latest_cluster_end_cm
                    and cluster.end * SPACING_CM >= c.latest_cluster_start_cm]
        if (any(sum(c is other for other, _ in overlaps) > 1 for c in contacts)
                or any(sum(i == j for _, j in overlaps) > 1 for i in range(len(clusters)))
                or sum(c.length * SPACING_CM >= self.config.min_foot_length for c in clusters) > 2):
            self.boundary_reason = "ambiguous_contact_merge_or_split"
            self.break_continuity()
            self._recovering = True
            return []
        matches = {c.contact_id: i for c, i in overlaps}
        used = set(matches.values())
        distances = sorted((abs(c.latest_centroid - cluster.centroid_cm), c.contact_id, i)
                           for c in contacts if c.contact_id not in matches
                           for i, cluster in enumerate(clusters) if i not in used)
        for distance, cid, i in distances:
            if distance <= 6 * SPACING_CM and cid not in matches and i not in used:
                matches[cid] = i
                used.add(i)
        for c in contacts:
            if c.contact_id in matches:
                self._observe(c, clusters[matches[c.contact_id]], time_s)
            elif c.out_time is None:
                c.out_time = time_s
                c.out_hold_s = hold
        for i, cluster in enumerate(clusters):
            if i not in used:
                self._new_contact(cluster, time_s)

        for c in list(self.active_contacts.values()):
            end = c.out_time if c.out_time is not None else time_s
            if (not c.is_initial_baseline and not c.touch_queued
                    and c.touch_time is not None and c.seen_count >= 8
                    and c.peak_length_cm >= self.config.min_foot_length
                    and end - c.touch_time + 1e-9 >= self.config.min_contact_time / 1000):
                c.touch_queued = True
                c.status = "confirmed"
                self._pending.append(GaitStepEvent("touch", c, time_s))
            # Debounce observed interruptions. Configured minimum flight is
            # applicable only when the entire optical area is clear.
            if c.out_time is not None and time_s - c.out_time + 1e-9 >= c.out_hold_s:
                self._finish_contact(c, time_s)

        # No event at/after an unresolved earlier boundary may be committed.
        unresolved = []
        for c in self.active_contacts.values():
            if not c.touch_queued and not c.is_initial_baseline and c.touch_time is not None:
                unresolved.append(c.touch_time)
            if c.out_time is not None:
                unresolved.append(c.out_time)
        watermark = min(unresolved, default=time_s + 1e-9)
        self._pending.sort(key=lambda e: (event_time(e), e.kind == "touch"))
        ready = []
        while self._pending and event_time(self._pending[0]) < watermark:
            event = self._pending.pop(0)
            c = event.contact
            if event.kind == "touch":
                self._assign_label(c)
                self.touch_count += 1
            elif not c.is_initial_baseline:
                self.lift_count += 1
                c.status = "lifted"
                c.contact_duration = c.lift_time - c.touch_time
            ready.append(event)
        return ready

    def _finish_contact(self, c, time_s):
        c.lift_time = c.out_time
        if c.touch_queued or c.is_initial_baseline:
            self._pending.append(GaitStepEvent("lift", c, time_s))
        elif c.touch_time is not None:
            self.rejected_contacts.append({
                "contact_id": c.contact_id, "touch_time_s": c.touch_time,
                "lift_time_s": c.lift_time, "reason": "contact_below_time_or_size_threshold",
            })
        del self.active_contacts[c.contact_id]


def event_time(event):
    return event.contact.touch_time if event.kind == "touch" else event.contact.lift_time
