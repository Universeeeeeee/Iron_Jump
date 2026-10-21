"""Reproducible isolated sparse-processing experiments; never opens hardware."""
import argparse
from collections import deque
from dataclasses import asdict, is_dataclass, replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / 'baseline'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from qtpy.QtCore import QCoreApplication, Qt
from hardware.sensor_frame import DeviceLayout, SensorSegment, SensorFrame
from hardware.walking_preflight import PreparedDevice, RuntimeBeamEvidence
from hardware.beam_quality import BeamQualityPolicy
from engine.device_quality_session import DeviceQualitySession
from engine.overground_session import OvergroundSession
from engine.modes.walking_processor import WalkingProcessor
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from candidates import Decoder, CancelledRuntime, SegmentClusters, processor_class, RetirementShadow, enabled

APP = QCoreApplication.instance() or QCoreApplication([])
VARIANTS = ('baseline', 'decode_full', 'decode_segments', 'runtime', 'idle', 'clusters', 'combined')
CALLBACK_ERRORS = []


def callback_error(kind, value, tb):
    CALLBACK_ERRORS.append(''.join(traceback.format_exception(kind, value, tb)))


sys.excepthook = callback_error


def feed_quality(quality, frame):
    quality.on_frame(frame)
    if CALLBACK_ERRORS:
        raise RuntimeError(CALLBACK_ERRORS[-1])


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def canonical(value):
    if is_dataclass(value):
        return canonical(asdict(value))
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, bytes):
        return {'bytes': value.hex()}
    if isinstance(value, (list, tuple, deque)):
        return [canonical(x) for x in value]
    if isinstance(value, set):
        return sorted(canonical(x) for x in value)
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    return value


def digest(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def state(p):
    return {k: v for k, v in p.__dict__.items()
            if not k.startswith('_exp_') and k not in ('_groups', '_clusters')}


def first_diff(a, b, path=''):
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return None if np.array_equal(a, b) else path
    if type(a) != type(b):
        return path + ':type'
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return path + ':keys:' + repr(a.keys() ^ b.keys())
        for k in a:
            d = first_diff(a[k], b[k], path + '/' + str(k))
            if d:
                return d
    elif isinstance(a, (list, tuple, deque)):
        if len(a) != len(b):
            return path + ':length'
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, path + '/' + str(i))
            if d:
                return d
    elif is_dataclass(a):
        return first_diff(a.__dict__, b.__dict__, path)
    elif a != b:
        return path + ':' + repr(a)[:120] + '!=' + repr(b)[:120]
    return None


def assert_equal(a, b, context):
    # Fast native/dataclass equality first, detailed traversal only on failure.
    try:
        if a == b:
            return
    except (ValueError, TypeError):
        pass
    difference = first_diff(a, b)
    if difference:
        raise AssertionError((context, difference))


def make_frame(layout, n, blocked=(), *, stream='synthetic', valid=None, flags=(), dropped=0):
    bits = bytearray(layout.bit_count)
    for low, high in blocked:
        bits[low:high + 1] = b'\x01' * (high - low + 1)
    wire = bytearray(layout.payload_bytes)
    for physical, seg in enumerate(layout.segments):
        part = bits[physical * 96:(physical + 1) * 96]
        if seg.reversed:
            part = part[::-1]
        for i in range(12):
            wire[seg.wire_index * 12 + i] = sum((1 - part[i * 8 + j]) << j for j in range(8))
    return SensorFrame(stream, layout, n & 0xFFFFFFFF, n, n * 1_000_000,
                       bytes(bits), valid if valid is not None else b'\1' * layout.bit_count,
                       bytes(wire), dropped, flags)


def synthetic(name, count=60000, modules=8, special_layout=False):
    if special_layout:
        order = list(reversed(range(modules)))
        layout = DeviceLayout(tuple(SensorSegment(str(i), order[i], i * 1.13,
                                                  .0101 + i * .00001, bool(i % 2))
                                    for i in range(modules)), (0,))
    else:
        layout = DeviceLayout.linear(modules)
    frames = []
    rng = np.random.default_rng(821)
    # Cache templates; frame generation is outside all measured intervals.
    templates = {}
    for n in range(count):
        period = n % 3000
        ranges = []
        if name == 'sparse':
            # Stationary repeated contacts across a seam: do not synthesize a
            # return to the origin that legitimately ends the running session.
            base = min(90, layout.bit_count - 25)
            if 300 <= period < 650:
                ranges = [(base, base + 20)]
            elif 800 <= period < 1100:
                ranges = [(base, base + 20)]
        elif name == 'cross':
            # One monotonic pass, with ten 1.7s contacts over 60 device seconds.
            if 300 <= n % 6000 < 2000:
                lo = min(70 + (n // 6000) * 20, layout.bit_count - 25)
                ranges = [(lo, lo + 24)]
        elif name == 'plateau':
            if count // 5 <= n < count * 4 // 5:
                ranges = [(min(100, layout.bit_count - 25), min(124, layout.bit_count - 1))]
        elif name == 'stress':
            # Every frame changes in every segment, with spatially dense runs.
            ranges = [(s * 96 + (n % 3), s * 96 + 92 + (n % 3)) for s in range(modules)]
        elif name == 'edges':
            q = n % 700
            if 20 <= q < 31 or 100 <= q < 109:
                ranges = [(10, 25)]
            elif 150 <= q < 280:
                ranges = [(max(0, layout.bit_count - 105), layout.bit_count - 80)] if modules > 1 else [(70, 90)]
            elif 310 <= q < 340:
                ranges = [(0, 95)]
            elif 400 <= q < 450:
                start = int(rng.integers(0, layout.bit_count - 25))
                ranges = [(start, start + 24)]
        key = tuple(ranges)
        if key not in templates:
            templates[key] = make_frame(layout, 0, ranges)
        flags = ()
        valid = b'\1' * layout.bit_count
        sample = n
        dropped = 0
        stream = 'synthetic'
        if name == 'edges':
            if n % 997 == 996:
                flags = ('frame_gap',); sample += 2; dropped = 2
            if n % 1601 == 1600:
                flags = ('crc_error',); valid = bytes(layout.bit_count)
            if n % 1801 == 1800:
                stream = 'restart'
        frames.append(replace(templates[key], frame_index=sample & 0xFFFFFFFF, sample_index=sample,
                              received_monotonic_ns=sample * 1_000_000, quality_flags=flags,
                              valid_bits=valid, dropped_frames_before=dropped, stream_id=stream))
    return layout, frames


def recorded(name):
    folder = HERE / 'inputs' / name
    meta = json.loads((folder / 'report.json').read_text())['report_config_snapshot']
    device = meta['device']; g = device['layout']
    layout = DeviceLayout(tuple(SensorSegment(**s) for s in g['segments']), tuple(g['invalid_bit_indices']))
    with np.load(folder / 'raw_frames.npz') as archive:
        data = {key: archive[key] for key in archive.files}
        indices = data['sample_indices']
        selected = np.flatnonzero(indices > device['checked_sample_index'])
        frames = [SensorFrame(device['stream_id'], layout, int(data['frame_indices'][k]),
                              int(indices[k]), int(data['received_ns'][k]), data['bits'][k].tobytes(),
                              b'\1' * layout.bit_count, data['wire'][k].tobytes()) for k in selected]
    return layout, frames, meta


def config_for(mode, meta=None, auto=False):
    cls = WalkingConfig if mode == 'walk' else OvergroundRunningConfig
    if meta:
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in meta.items() if k in fields and fields[k].init})
    return cls() if auto else cls(stop_type='Software command', starting_foot='Left')


def pipeline(mode, layout, frames, variant, meta=None):
    cfg = config_for(mode, meta)
    policy = BeamQualityPolicy(**meta['device']['policy']) if meta else BeamQualityPolicy()
    bad = tuple(meta['device']['bad_indices']) if meta else ()
    dev = PreparedDevice(layout, frames[0].stream_id, frames[0].sample_index - 1, 0,
                         policy.samples, policy=policy, bad_indices=bad)
    quality = DeviceQualitySession(cfg, policy)
    quality._segments.observe(frames[0])
    quality.context = dev
    if enabled(variant, 'runtime'):
        quality._runtime = CancelledRuntime(policy)
    cls = WalkingProcessor if mode == 'walk' else OvergroundRunningProcessor
    session = OvergroundSession(cfg, processor_class(cls, variant))
    session.start_prepared(dev)
    def deliver(raw, processed, uncertain):
        if processed is None:
            session.archive_raw_frame(raw, raw_only=True)
        else:
            session.on_frame(processed, raw, uncertain)
    quality.frame_ready.connect(deliver, Qt.DirectConnection)
    return quality, session


def compare_runtime(a, b, context):
    assert a.last_frame == b.last_frame and a.healthy_samples == b.healthy_samples, context
    for key in ('_counts', '_transitions', '_previous'):
        assert np.array_equal(getattr(a, key), getattr(b, key)), (context, key)
    assert len(a._window) == len(b._window), context
    if a._window:
        assert all(np.array_equal(x, y) for x, y in zip(a._window[-1], b._window[-1])), context


def correctness(name, layout, frames, mode, variant, meta=None):
    base_q, base = pipeline(mode, layout, frames, 'baseline', meta)
    cand_q, cand = pipeline(mode, layout, frames, variant, meta)
    left, right = [], []
    for session, q, dest in ((base, base_q, left), (cand, cand_q, right)):
        q.frame_ready.connect(lambda raw, processed, uncertain, dest=dest:
                             dest.append(('quality_frame', raw, processed, uncertain)), Qt.DirectConnection)
        q.notice.connect(lambda x, dest=dest: dest.append(('notice', canonical(x))), Qt.DirectConnection)
        session.snapshot.connect(lambda x, dest=dest: dest.append(('snapshot', canonical(x))), Qt.DirectConnection)
        session.visual.connect(lambda x, dest=dest: dest.append(('visual', canonical(x))), Qt.DirectConnection)
        session.finished.connect(lambda x, dest=dest: dest.append(('finished', x)), Qt.DirectConnection)
    decode_variant = ('decode_full' if enabled(variant, 'decode_full') else
                      'decode_segments' if enabled(variant, 'decode_segments') else 'baseline')
    decoder = Decoder(layout, decode_variant)
    stream_hash = hashlib.sha256()
    for f in frames:
        changed = replace(f, contact_bits=decoder.decode(f.wire_payload)) if decode_variant != 'baseline' else f
        assert changed == f, (name, variant, f.sample_index, 'decoded_frame')
        feed_quality(base_q, f); feed_quality(cand_q, changed)
        context = (name, mode, variant, f.sample_index)
        assert_equal(state(base.processor), state(cand.processor), context)
        compare_runtime(base_q._runtime, cand_q._runtime, context)
        for key in ('_events', '_event_count', '_last_event_key', '_last_event',
                    '_runtime_suspicious_indices', 'done'):
            assert_equal(getattr(base_q, key), getattr(cand_q, key), (context, key))
        assert_equal(left, right, (context, 'emitted'))
        # Hash each frame's emitted evidence before objects can mutate later.
        stream_hash.update(digest(left).encode()); left.clear(); right.clear()
    base.halt(); cand.halt()
    assert_equal(left, right, (name, mode, variant, 'flush emitted'))
    assert_equal(state(base.processor), state(cand.processor), (name, mode, variant, 'flush state'))
    for (x, y), (u, v) in zip(base_q._runtime._window, cand_q._runtime._window):
        assert np.array_equal(x, u) and np.array_equal(y, v)
    report_a, report_b = base.build_report('manual'), cand.build_report('manual')
    assert_equal(asdict(report_a), asdict(report_b), (name, mode, variant, 'complete_report'))
    assert list(base.frames) == list(cand.frames) and list(base.timestamps) == list(cand.timestamps)
    return {'case': name, 'mode': mode, 'variant': variant, 'frames': len(frames), 'exact': True,
            'idle_hits': getattr(cand.processor, '_exp_idle_hits', 0),
            'runtime_count_skips': getattr(cand_q._runtime, '_exp_count_skips', 0),
            'report_sha256': digest(asdict(report_a)), 'stream_sha256': stream_hash.hexdigest()}


def decoder_checks():
    rows = []
    for modules in (1, 3, 8):
        for custom in (False, True):
            layout, frames = synthetic('edges', 2100, modules, custom)
            for variant in ('decode_full', 'decode_segments'):
                decoder = Decoder(layout, variant)
                previous_bits = None
                for j, f in enumerate(frames):
                    if j == 1000:
                        decoder.reset(); previous_bits = None
                    bits = decoder.decode(f.wire_payload)
                    # Independent bit-by-bit wire oracle, not the production lookup table.
                    oracle = bytes(1 - ((f.wire_payload[s.wire_index * 12 + (95-i if s.reversed else i) // 8]
                                         >> ((95-i if s.reversed else i) % 8)) & 1)
                                   for s in layout.segments for i in range(96))
                    assert bits == oracle == f.contact_bits
                    if variant == 'decode_segments' and previous_bits is not None:
                        changed = sum((a != b) << i for i, (a, b) in enumerate(zip(bits, previous_bits)))
                        on = sum((a == 1 and b == 0) << i for i, (a, b) in enumerate(zip(bits, previous_bits)))
                        off = sum((a == 0 and b == 1) << i for i, (a, b) in enumerate(zip(bits, previous_bits)))
                        assert decoder.delta == (changed, on, off)
                    previous_bits = bits
                try:
                    decoder.decode(b'')
                    raise AssertionError('invalid length accepted')
                except ValueError:
                    pass
                rows.append({'modules': modules, 'custom': custom, 'variant': variant,
                             'frames': len(frames), 'independent_bit_oracle': True})
    return rows


def observations(name, layout, frames):
    same = sum(a.wire_payload == b.wire_payload for a, b in zip(frames, frames[1:]))
    seg_same = sum(a.wire_payload[s:s+12] == b.wire_payload[s:s+12]
                   for a, b in zip(frames, frames[1:]) for s in range(0, layout.payload_bytes, 12))
    return {'case': name, 'frames': len(frames), 'wire_same_pct': 100 * same / max(1, len(frames)-1),
            'wire_segment_same_pct': 100 * seg_same / max(1, (len(frames)-1)*len(layout.segments)),
            'raw_empty_pct': 100 * sum(b'\1' not in f.contact_bits for f in frames) / len(frames),
            'input_sha256': digest([(f.sample_index, f.contact_bits, f.wire_payload) for f in frames])}


def runtime_checks():
    rows = []
    for name in ('empty', 'plateau', 'edges', 'stress'):
        layout, frames = synthetic(name, 8000, 8)
        a, b = RuntimeBeamEvidence(BeamQualityPolicy()), CancelledRuntime(BeamQualityPolicy())
        for f in frames:
            assert a.observe(f) == b.observe(f)
            compare_runtime(a, b, (name, f.sample_index))
        for (x, y), (u, v) in zip(a._window, b._window):
            assert np.array_equal(x, u) and np.array_equal(y, v)
        rows.append({'case': name, 'frames': len(frames), 'every_count_and_delta_exact': True})
    return rows


def benchmark(name, variant, target):
    if name.startswith('field_'):
        layout, frames, meta = recorded(name)
        mode = 'run' if name == 'field_run_20261015_02' else 'walk'
    else:
        layout, frames = synthetic(name)
        meta = None; mode = 'run'
    stage_times = []
    if target == 'pipeline':
        quality, session = pipeline(mode, layout, frames, variant, meta)
        decode_variant = ('decode_full' if enabled(variant, 'decode_full') else
                          'decode_segments' if enabled(variant, 'decode_segments') else 'baseline')
        decoder = Decoder(layout, decode_variant)
        def run():
            for f in frames:
                f = replace(f, contact_bits=decoder.decode(f.wire_payload))
                feed_quality(quality, f)
            session.halt()
    elif target == 'decode':
        decoder = Decoder(layout, variant)
        def run():
            for f in frames:
                decoder.decode(f.wire_payload)
    elif target == 'runtime':
        runtime = CancelledRuntime(BeamQualityPolicy()) if variant == 'runtime' else RuntimeBeamEvidence(BeamQualityPolicy())
        def run():
            for f in frames:
                runtime.observe(f)
    elif target in {'formal_processor', 'formal_clusters'}:
        # Stage inputs must be the actual quality-masked, filtered frames,
        # including each formal frame's masked-contact argument. Preparing
        # this stream is not part of the scored stage CPU interval.
        prepare_q, prepare_s = pipeline(mode, layout, frames, 'baseline', meta)
        formal = []
        original_process = prepare_s.processor.process
        def capture(f, observation=None, *, masked_contact=False):
            assert observation is None
            formal.append((f, masked_contact))
            return original_process(f, masked_contact=masked_contact)
        prepare_s.processor.process = capture
        for f in frames:
            feed_quality(prepare_q, f)
        prepare_s.halt()
        assert len(formal) == len(frames), (name, 'formal stage input coverage')
        cls = WalkingProcessor if mode == 'walk' else OvergroundRunningProcessor
        processor = processor_class(cls, variant)(config_for(mode, meta), prepare_s.processor.device)
        if target == 'formal_processor':
            def run():
                for f, masked in formal:
                    processor.process(f, masked_contact=masked)
        else:
            method = processor._clusters if mode == 'walk' else processor._groups
            def run():
                for f, _ in formal:
                    method(f.contact_bits)
    else:
        cls = WalkingProcessor if mode == 'walk' else OvergroundRunningProcessor
        dev = PreparedDevice(layout, frames[0].stream_id, frames[0].sample_index-1, 0, 3000)
        processor = processor_class(cls, variant)(config_for(mode, meta), dev)
        if target == 'clusters':
            method = processor._clusters if mode == 'walk' else processor._groups
            def run():
                for f in frames:
                    method(f.contact_bits)
        else:
            def run():
                for f in frames:
                    processor.process(f)
    # Warm interpreter and Qt code paths using an independent short instance.
    warm_q, warm_s = pipeline(mode, layout, frames, 'baseline', meta)
    for f in frames[:100]:
        feed_quality(warm_q, f)
    warm_s.halt()
    cpu = time.thread_time_ns(); wall = time.perf_counter_ns()
    run()
    wall = time.perf_counter_ns() - wall; cpu = time.thread_time_ns() - cpu
    result = {'case': name, 'variant': variant, 'target': target, 'frames': len(frames),
              'cpu_ns': cpu, 'wall_ns': wall, 'cpu_us_per_frame': cpu/len(frames)/1000,
              'wall_us_per_frame': wall/len(frames)/1000, 'source_root': str(HERE/'baseline'),
              'profile_enabled': False, 'includes_stop_flush': target == 'pipeline'}
    if variant == 'combined':
        result['combined_features'] = os.environ['IRON_SPARSE_FEATURES'].split(',')
    if target == 'pipeline':
        result.update(report_sha256=digest(asdict(session.build_report('manual'))),
                      accepted_frames=session.total_frames, retained_frames=len(session.frames),
                      last_formal_sample=session.processor.last_sample,
                      finished_reason=session.processor.finished_reason,
                      idle_hits=getattr(session.processor, '_exp_idle_hits', 0))
        assert session.total_frames == len(frames), (name, variant, 'accepted raw count')
        assert session.processor.last_sample == frames[-1].sample_index, (name, variant, 'incomplete formal coverage')
        assert session.processor.finished_reason is None, (name, variant, 'unexpected early termination')
    return result


def verify_sources():
    manifest = json.loads((HERE/'manifest.json').read_text())
    errors = []
    for name, expected in manifest['production_sources'].items():
        for prefix in (ROOT, HERE/'baseline'):
            if hashlib.sha256((prefix/name).read_bytes()).hexdigest() != expected:
                errors.append(str(prefix/name))
    for name, expected in manifest['inputs'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            errors.append(name)
    for name, expected in json.loads((HERE/'input_package.json').read_text())['files'].items():
        if hashlib.sha256((HERE/name).read_bytes()).hexdigest() != expected:
            errors.append(name)
    assert not errors, errors
    return {'sources_and_inputs_unchanged': True, 'python_sources': len(manifest['production_sources'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('check', 'bench', 'suite', 'verify'))
    parser.add_argument('--case', default='sparse')
    parser.add_argument('--variant', choices=VARIANTS, default='baseline')
    parser.add_argument('--target', choices=('pipeline', 'decode', 'runtime', 'clusters', 'processor',
                                            'formal_processor', 'formal_clusters'), default='pipeline')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'bench':
        result = benchmark(args.case, args.variant, args.target)
    elif args.action == 'verify':
        result = verify_sources()
    elif args.action == 'check':
        result = {'decoders': decoder_checks(), 'runtime': runtime_checks(), 'pipeline': []}
        for name in ('empty', 'sparse', 'cross', 'edges'):
            layout, frames = synthetic(name, 2100)
            for mode in ('walk', 'run'):
                for variant in ('runtime', 'idle', 'clusters'):
                    row = correctness(name, layout, frames, mode, variant)
                    result['pipeline'].append(row); print(json.dumps(row), flush=True)
        for name, mode in (('field_run_20261015_02', 'run'), ('field_walk_full_02', 'walk')):
            layout, frames, meta = recorded(name)
            for variant in ('decode_full', 'decode_segments', 'runtime', 'idle', 'clusters'):
                row = correctness(name, layout, frames, mode, variant, meta)
                result['pipeline'].append(row); print(json.dumps(row), flush=True)
        result['source_verification'] = verify_sources()
    else:
        raise SystemExit('Use run_suite.py for orchestration')
    if args.output:
        dump(args.output, result)
    print(json.dumps(result if args.action != 'check' else {'all_exact': True,
                     'pipeline_cases': len(result['pipeline'])}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        traceback.print_exc()
        raise SystemExit(1)
