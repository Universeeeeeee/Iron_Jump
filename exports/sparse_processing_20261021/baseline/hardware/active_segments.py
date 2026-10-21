"""Select non-zero protocol slots during preflight; never rewrite raw samples."""
from dataclasses import asdict, replace
from hardware.sensor_frame import DeviceLayout


class ActiveSegments:
    def __init__(self, observation_samples):
        self.observation_samples = observation_samples
        self.source_layout = None
        self.last_frame = None
        self.indices = ()
        self.layout = None
        self._zero_runs = []
        self._snapshot = {}
        self.regions = ()

    def reset(self):
        self.last_frame = None
        self._zero_runs = [0] * len(self.source_layout.segments) if self.source_layout else []
        self._select(tuple(range(len(self._zero_runs))))

    def _select(self, indices):
        self.indices = indices
        if not self.source_layout:
            self.layout = None
            return
        if len(indices) == len(self.source_layout.segments):
            self.layout = self.source_layout
        elif indices:
            segments = tuple(replace(self.source_layout.segments[s], wire_index=i) for i, s in enumerate(indices))
            invalid = tuple(i * 96 + b for i, s in enumerate(indices) for b in range(96)
                            if s * 96 + b in self.source_layout.invalid_bit_indices)
            self.layout = DeviceLayout(segments, invalid)
        else:
            self.layout = None
        self._snapshot = {
            'criterion': 'all_zero_during_preflight_window',
            'observation_samples': self.observation_samples,
            'source_segment_count': len(self.source_layout.segments),
            'source_segment_indices': indices,
            'excluded_segment_indices': tuple(s for s in range(len(self.source_layout.segments)) if s not in indices),
            'source_layout': asdict(self.source_layout),
        }
        regions = []
        region = 0
        for i, s in enumerate(indices):
            if i and s != indices[i - 1] + 1:
                region += 1
            regions.append(region)
        self.regions = tuple(regions)

    def observe(self, frame):
        previous = self.last_frame
        if frame.layout != self.source_layout:
            self.source_layout = frame.layout
            self.reset()
        elif previous and (frame.stream_id != previous.stream_id or frame.sample_index != previous.sample_index + 1):
            self.reset()
        self.last_frame = frame
        valid = (len(frame.contact_bits) == frame.layout.bit_count
                 and len(frame.valid_bits) == frame.layout.bit_count and all(frame.valid_bits)
                 and not frame.dropped_frames_before
                 and not any(f != 'all_beams_blocked' for f in frame.quality_flags))
        if not valid:
            self.reset()
            self.last_frame = frame
            return self.project(frame)
        # Contact semantics are inverted from wire bits: 96 blocked bits == 12 zero bytes.
        for s in range(len(self._zero_runs)):
            self._zero_runs[s] = (min(self.observation_samples, self._zero_runs[s] + 1)
                                  if frame.contact_bits[s * 96:(s + 1) * 96] == b'\x01' * 96 else 0)
        indices = tuple(s for s, run in enumerate(self._zero_runs) if run < self.observation_samples)
        if indices != self.indices:
            self._select(indices)
        return self.project(frame)

    def project(self, frame):
        if self.layout is None:
            return None
        if self.layout == frame.layout:
            return frame
        payload = b''.join(frame.wire_payload[self.source_layout.segments[s].wire_index * 12:
                                             (self.source_layout.segments[s].wire_index + 1) * 12] for s in self.indices)
        return replace(frame, layout=self.layout,
                       contact_bits=b''.join(frame.contact_bits[s * 96:(s + 1) * 96] for s in self.indices),
                       valid_bits=b''.join(frame.valid_bits[s * 96:(s + 1) * 96] for s in self.indices),
                       wire_payload=payload)

    def snapshot(self):
        return self._snapshot
