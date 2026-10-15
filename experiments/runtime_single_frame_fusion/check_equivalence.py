"""Per-sample reference, independent integer oracle, ownership and quality audit checks."""
import json
from collections import deque
from dataclasses import replace
from pathlib import Path
import sys
import time
from types import MethodType

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(HERE)]
import numpy as np
from qtpy.QtCore import QCoreApplication
from hardware.sensor_frame import DeviceLayout, SensorFrame, SensorSegment
from hardware.beam_quality import BeamQualityPolicy
from hardware.walking_preflight import RuntimeBeamEvidence, PreparedDevice
from fused_runtime import runtime_class, warmup
from install_variant import install


class IntegerOracle:
    """Pure Python byte/integer arithmetic, independent of NumPy/JIT updates."""
    def __init__(self, samples):
        self.samples = samples
        self.last = None
        self.reset()

    def reset(self):
        self.window = deque()
        self.counts, self.transitions = [], []
        self.previous = None

    def observe(self, frame):
        last, self.last = self.last, frame
        if last is not None and (frame.stream_id != last.stream_id or frame.layout != last.layout
                                 or frame.sample_index - last.sample_index != 1):
            self.reset()
        if (len(frame.contact_bits) != frame.layout.bit_count
                or len(frame.valid_bits) != frame.layout.bit_count or 0 in frame.valid_bits
                or frame.dropped_frames_before or set(frame.quality_flags) - {'all_beams_blocked'}):
            self.reset()
            return False
        bits = frame.contact_bits
        if self.previous is None:
            self.counts = [0] * len(bits)
            self.transitions = [0] * len(bits)
            changes = bytes(len(bits))
        else:
            changes = bytes(x ^ y for x, y in zip(bits, self.previous))
        self.window.append((bits, changes))
        old, delta = self.window.popleft() if len(self.window) > self.samples else (bytes(len(bits)), bytes(len(bits)))
        for i, bit in enumerate(bits):
            self.counts[i] += bit - old[i]
            self.transitions[i] += changes[i] - delta[i]
        self.previous = bits
        return True


def synthetic(modules, boundaries=True):
    layout = DeviceLayout.linear(modules)
    for n in range(6500):
        bits = bytearray(layout.bit_count)
        bits[0] = int(n < 1300 or n >= 2900)
        bits[1] = n % 2 if 1100 <= n < 1140 else 0
        if 1800 <= n < 2200:
            bits[20:30] = b'\1' * 10
        # Hold and then clear the entire field, including accepted quality flag.
        if 2300 <= n < 2400:
            bits[:] = b'\1' * len(bits)
        frame = SensorFrame('synthetic', layout, n, n, n * 1000000, bytes(bits),
                            b'\1' * len(bits), np.packbits(1 - np.frombuffer(bits, np.uint8), bitorder='little').tobytes(),
                            quality_flags=('all_beams_blocked',) if 2300 <= n < 2400 else ())
        if boundaries:
            if n == 3300: frame = replace(frame, sample_index=n + 2)
            if n == 3400: frame = replace(frame, sample_index=n - 1)
            if n == 3500: frame = replace(frame, stream_id='restart')
            if n == 3600: frame = replace(frame, layout=DeviceLayout.linear(modules, wire_order=tuple(range(modules, 0, -1))) if modules > 1 else DeviceLayout.linear(2))
            if n == 3700: frame = replace(frame, dropped_frames_before=1)
            if n == 3800: frame = replace(frame, valid_bits=b'\0' + frame.valid_bits[1:])
            if n == 3900: frame = replace(frame, contact_bits=frame.contact_bits[:-1])
            if n == 4000: frame = replace(frame, valid_bits=frame.valid_bits[:-1])
            if n == 4100: frame = replace(frame, quality_flags=('checksum_error',))
        yield frame


def recorded(folder):
    meta_path = folder / 'metadata.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else json.loads((folder / 'report.json').read_text(encoding='utf-8'))['report_config_snapshot']
    d = meta['device']
    layout = DeviceLayout(tuple(SensorSegment(**s) for s in d['layout']['segments']), tuple(d['layout']['invalid_bit_indices']))
    path = folder / ('matched_usb.npz' if (folder / 'matched_usb.npz').exists() else 'raw_frames.npz')
    with np.load(path) as raw:
        bits = raw['bits']
        samples = raw['sample_indices'] if 'sample_indices' in raw else raw['frame_indices'] if 'frame_indices' in raw else np.arange(len(bits)) + d['checked_sample_index'] + 1
        counters = raw['frame_indices'] if 'frame_indices' in raw else samples
        wire = raw['wire'] if 'wire' in raw else np.packbits(1 - bits, axis=1, bitorder='little')
        for index, n, row, payload in zip(counters, samples, bits, wire):
            yield SensorFrame(d['stream_id'], layout, int(index), int(n), int(n) * 1000000,
                              row.tobytes(), b'\1' * layout.bit_count, payload.tobytes())


def check(name, frames, oracle=False, policy=None):
    policy = policy or BeamQualityPolicy()
    variants = [RuntimeBeamEvidence(policy), runtime_class('B')(policy), runtime_class('C')(policy)]
    independent = IntegerOracle(policy.samples) if oracle else None
    masks = [None] * 3
    snapshots = []
    count = 0
    for frame in frames:
        returns = [v.observe(frame) for v in variants]
        assert returns == [returns[0]] * 3, (name, frame.sample_index, 'return')
        a = variants[0]
        if independent:
            assert independent.observe(frame) == returns[0]
            assert a._counts.tolist() == independent.counts
            assert a._transitions.tolist() == independent.transitions
        for j, v in enumerate(variants):
            assert v.last_frame == a.last_frame and v.healthy_samples == a.healthy_samples
            for key in ('_counts', '_transitions', '_previous'):
                assert np.array_equal(getattr(v, key), getattr(a, key)), (name, frame.sample_index, key)
            if a.healthy_samples < policy.samples:
                new_mask, changed = None, False
            else:
                new_mask = (v._counts >= policy.samples * .95) | (v._transitions >= 20)
                changed = not np.array_equal(new_mask, masks[j])
                if j:
                    assert np.array_equal(new_mask, v.suspicious_mask)
                    assert changed == v.mask_changed, (name, frame.sample_index, 'mask change')
            masks[j] = new_mask
            assert np.array_equal(masks[j], masks[0])
            assert len(a._window) == len(v._window)
            if a._window:
                assert all(np.array_equal(x, y) for x, y in zip(a._window[-1], v._window[-1]))
            if count % 1000 == 0:
                for expected, actual in zip(a._window, v._window):
                    assert all(np.array_equal(x, y) for x, y in zip(expected, actual))
                if v._window:
                    snapshots.append((v._window[-1][1], v._window[-1][1].copy()))
                if j and v.suspicious_mask.size:
                    snapshots.append((v.suspicious_mask, v.suspicious_mask.copy()))
        count += 1
    assert all(np.array_equal(view, saved) for view, saved in snapshots), (name, 'historical buffer mutated')
    result = {'name': name, 'frames': count, 'exact': True, 'independent_integer_oracle': oracle,
              'window_samples': policy.samples,
              'retained_ownership_snapshots': len(snapshots)}
    print(json.dumps(result), flush=True)
    return result


def quality_check(seconds):
    from engine.device_quality_session import DeviceQualitySession
    from config.overground_running_config import OvergroundRunningConfig
    policy = BeamQualityPolicy(observation_seconds=seconds)
    gates = []
    for variant in 'ABC':
        install(variant)
        gate = DeviceQualitySession(OvergroundRunningConfig(), policy)
        gate.on_frame = MethodType(DeviceQualitySession.on_frame, gate)
        initial = next(synthetic(1, boundaries=False))
        gate._segments.observe(initial)
        gate.context = PreparedDevice(initial.layout, initial.stream_id, 0, 0, policy.samples, policy=policy)
        gates.append(gate)
    # Do not reset the window at the threshold/clear transitions.
    for frame in synthetic(1, boundaries=False):
        for gate in gates:
            gate.on_frame(frame)
        a = gates[0]
        for gate in gates[1:]:
            assert gate._events == a._events, (frame.sample_index, 'audit intervals')
            assert gate._event_count == a._event_count
            assert gate._last_event_key == a._last_event_key
            assert gate._runtime_suspicious_indices == a._runtime_suspicious_indices
            assert np.array_equal(gate._runtime_suspicious_mask, a._runtime_suspicious_mask)
    assert any(e['code'] == 'runtime_obstruction' for e in a._events)
    install('A')
    return {'frames': 6500, 'window_samples': policy.samples, 'audit_events': len(a._events), 'all_intermediate_quality_audits_exact': True}


if __name__ == '__main__':
    started = time.perf_counter()
    app = QCoreApplication([])
    compilation = warmup()
    results = [check('synthetic_' + str(n), synthetic(n), oracle=True,
                     policy=BeamQualityPolicy(observation_seconds=1)) for n in (1, 2, 4, 8)]
    folders = [ROOT / 'exports/ground_boundary_latency_20261014' / n for n in ('field_run_20261015_02', 'field_walk_full_02')]
    folders += [ROOT / 'exports' / name / mode for name in ('ground_field_20261009', 'walking_field_v16_20261009', 'ground_field_20261010_audit') for mode in ('run', 'walk')]
    for folder in folders:
        results.append(check(str(folder.relative_to(ROOT)), recorded(folder)))
    output = {'results': results, 'total_frames': sum(r['frames'] for r in results),
              'quality': [quality_check(seconds) for seconds in (1, 3)], 'compilation': compilation,
              'elapsed_seconds': time.perf_counter() - started,
              'all_checks_passed': True}
    (HERE / 'equivalence.json').write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print('ALL EXACT', output['total_frames'], flush=True)
