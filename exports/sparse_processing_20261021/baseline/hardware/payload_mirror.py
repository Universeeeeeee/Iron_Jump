"""Quarantine the independently observed 96-byte, 32-byte periodic wire alias.

This is a measurement-input guard, not a reconstruction of missing optical bits.
Raw frames are retained; phase alone or a single equal block is insufficient.
"""
from dataclasses import replace


def bit_distance(left, right):
    length = min(len(left), len(right))
    return (int.from_bytes(left[:length], 'little')
            ^ int.from_bytes(right[:length], 'little')).bit_count()


class PeriodicPayloadMirrorGuard:
    rule_version = 'isolated_32_byte_mirror_30ms_v1'

    def __init__(self, layout):
        self.layout = layout
        self.affected_indices = tuple(
            physical * 96 + i
            for physical, segment in enumerate(layout.segments)
            for i in range(96)
            if segment.wire_index * 96 + (95-i if segment.reversed else i) < 256)
        self.events = []
        self.tail_events = []
        self._previous = None
        self._pending = None
        self._evidence = []
        self._phase = None
        self._phase_evidence = []

    @staticmethod
    def _usable(frame):
        return (frame.layout.payload_bytes == 96 and len(frame.wire_payload) == 96 and all(frame.valid_bits)
                and not frame.dropped_frames_before and not frame.quality_flags)

    def _candidate(self, frame, previous):
        wire, before = frame.wire_payload, previous.wire_payload
        return (self._usable(frame) and self._usable(previous)
                and bit_distance(wire[:32], wire[64:]) <= 2
                and bit_distance(wire[:32], wire[64:]) < bit_distance(before[:32], before[64:]))

    def _quarantine(self, before, frame, after):
        wire, left, right = frame.wire_payload, before.wire_payload, after.wire_payload
        if (not self._usable(after) or not self._candidate(frame, after)
                or any(bit_distance(wire[a:b], neighbour[a:b]) > 2
                       for neighbour in (left, right) for a,b in ((32,64),(64,96)))):
            return ()
        n = frame.frame_index
        # Informative mirrored changes establish a phase; sparse one-beam
        # coincidences cannot establish it. Subsequent events need the same
        # complete signature and two neighbouring observations, not just phase.
        if min(bit_distance(wire[:32], w[:32]) for w in (left,right)) >= 8:
            self._evidence.append(n)
            self._evidence = self._evidence[-3:]
            if (len(self._evidence) == 3 and len({i % 30 for i in self._evidence}) == 1):
                self._phase = n % 30
                self._phase_evidence = list(self._evidence)
        if self._phase is None or n % 30 != self._phase:
            return ()
        self.events.append({'sample_index': frame.sample_index, 'frame_index': n,
            'rule_version': self.rule_version, 'wire_byte_range': [0,32],
            'mirror_source_byte_range': [64,96], 'period_samples': 30, 'phase': self._phase,
            'mismatch_bits': bit_distance(wire[:32],wire[64:]),
            'phase_evidence_frames': list(self._phase_evidence), 'action': 'exclude_confirmation_votes',
            'raw_reconstructed': False})
        return self.affected_indices

    def feed(self, frame):
        previous = self._previous
        continuous = (previous is not None and frame.stream_id == previous.stream_id
                      and frame.layout == previous.layout
                      and frame.sample_index == previous.sample_index + 1
                      and frame.frame_index == previous.frame_index + 1)
        ready = []
        if self._pending is not None:
            before, pending = self._pending
            affected = self._quarantine(before,pending,frame) if continuous else ()
            ready.append((pending, affected))
            self._pending = None
        if not continuous or not self._usable(frame):
            self._evidence.clear()
            self._phase = None
            self._phase_evidence.clear()
        if continuous and self._candidate(frame,previous):
            self._pending = (previous,frame)
        else:
            ready.append((frame, ()))
        self._previous = frame
        return ready

    def flush(self):
        ready = []
        if self._pending:
            frame = self._pending[1]
            if self._phase is not None and frame.frame_index % 30 == self._phase:
                self.tail_events.append({'sample_index':frame.sample_index,'frame_index':frame.frame_index,
                    'rule_version':self.rule_version,'wire_byte_range':[0,32],
                    'action':'unconfirmed_mirror_tail','raw_reconstructed':False})
                valid = bytearray(frame.valid_bits)
                for i in self.affected_indices:valid[i] = 0
                frame = replace(frame,valid_bits=bytes(valid),
                    quality_flags=frame.quality_flags+('unconfirmed_payload_mirror_tail',))
            ready.append((frame, ()))
        self._pending = None
        return ready

    def reset(self):
        ready = self.flush()
        self._previous = None
        self._evidence.clear()
        self._phase = None
        self._phase_evidence.clear()
        return ready
