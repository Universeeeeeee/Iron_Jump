"""Read-only synchronous oracle and coarse stage replays; never opens devices.

Tapes record top-level calls without timers. Timed replays read clocks only at
1000-raw-sample boundaries. Stage times are separate scopes, not nested sums.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from qtpy.QtCore import QCoreApplication
from config.walking_config import WalkingConfig
from engine.gait_engine import GaitEngine
from engine.device_quality_session import DeviceQualitySession
from engine.modes.walking_processor import WalkingProcessor
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import BeamQualityPolicy
from hardware.sensor_frame import DeviceLayout, SensorSegment, SensorFrame

NAMES = ['20261017_111818_dc83b931_walk_off', '20261017_112623_8416401b_walk_on',
         '20261017_113358_00ae9eca_walk_on', '20261017_113916_32a7af0d_walk_off']
REAL_CLOCK = time.perf_counter_ns


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def plain(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def equal(actual, expected, label):
    a, b = plain(actual), plain(expected)
    if a == b:
        return
    diffs = []
    def visit(x, y, path):
        if len(diffs) >= 12 or x == y:
            return
        if isinstance(x, dict) and isinstance(y, dict) and x.keys() == y.keys():
            for key in x:
                visit(x[key], y[key], path + '/' + key)
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            for i, (left, right) in enumerate(zip(x, y)):
                visit(left, right, path + '/' + str(i))
        else:
            diffs.append((path, str(x)[:200], str(y)[:200]))
    visit(a, b, '')
    raise AssertionError((label, diffs))


def state(processor):
    p = processor
    result = {k: len(getattr(p, k)) for k in ('contacts', 'active', 'timeline', '_ownership_groups',
              '_source_review_frames', '_narrow_candidates', '_narrow_unknown', '_candidate_decisions',
              '_touch_events', 'event_audit')}
    for k in ('positions', 'position_samples', 'valid_sample_intervals'):
        result['contact_' + k] = sum(len(getattr(c, k)) for c in p.contacts)
    return result


class Trial:
    def __init__(self, folder):
        self.folder = folder
        self.report, self.saved = read(folder / 'report.json'), read(folder / 'state.json')
        self.meta = self.report['report_config_snapshot']
        self.drain_ns = read(folder / 'measurement.json')['queue_final'][0]
        self.cfg = WalkingConfig(**{k: v for k, v in self.meta.items()
                                   if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
        self.evidence = read(folder / 'acquisition.json')
        assert not self.evidence['issues']
        with np.load(folder / 'raw_frames.npz') as archive:
            raw = {key: archive[key] for key in archive.files}
        self.start = self.meta['device']['checked_sample_index'] + 1
        self.end = self.start + self.meta['raw_buffer']['total_received_frames']
        assert not self.meta['raw_buffer']['truncated'] and self.meta['raw_buffer']['raw_only_tail_frames'] == 0
        assert np.array_equal(raw['sample_indices'], np.arange(len(raw['sample_indices'])))
        assert self.evidence['events'] == [['frame', i] for i in range(len(raw['sample_indices']))]
        layouts = {k: DeviceLayout(tuple(SensorSegment(**s) for s in v['segments']), tuple(v['invalid_bit_indices']))
                   for k, v in self.evidence['layouts'].items()}
        self.frames = []
        for i in range(self.end):
            info = self.evidence['frames'][i]
            self.frames.append(SensorFrame(info['stream_id'], layouts[info['stream_id']], int(raw['frame_indices'][i]),
                               i, int(raw['received_ns'][i]), raw['bits'][i].tobytes(), raw['valid_bits'][i].tobytes(),
                               raw['wire'][i].tobytes(), int(raw['dropped_frames_before'][i]), tuple(info['quality_flags'])))
        assert self.frames[self.start - 1].received_monotonic_ns == self.meta['device']['checked_monotonic_ns']
        self.manifest = {name: file_sha(folder / name) for name in ('raw_frames.npz', 'raw_archive.npz', 'acquisition.json', 'report.json', 'state.json')}
        self.clock = self.frames[0].received_monotonic_ns
        self.quality_tape, self.filter_tape, self.processor_tape = [], [], []
        self.output_map, self.states = [], []
        self.outer = -1

    def quality(self, parent=None):
        return DeviceQualitySession(self.cfg, BeamQualityPolicy(**self.meta['beam_quality']['preflight']['policy']), parent)

    def arm(self, quality):
        quality.arm_checked((quality._status()['device_key'], self.meta['beam_quality']['empty_field_acknowledged']))
        assert quality.context is not None

    def terminal_poll(self, quality):
        # Actual drained-queue observation, not a synthetic per-frame timestamp.
        # OFF4 took >1 s to drain after USB stopped and saved a timeout event.
        # The poll's exact dispatch time is unavailable; this preserves its effect.
        self.clock = self.drain_ns
        quality.poll()

    def check_quality(self, quality):
        equal(quality.snapshot(), self.saved['quality'], 'quality history/context')
        runtime = quality._runtime
        window = hashlib.sha256()
        for bits, changes in runtime._window:
            window.update(bits.tobytes()); window.update(changes.tobytes())
        for key, value in [('runtime_counts', runtime._counts.tolist()), ('runtime_transitions', runtime._transitions.tolist()),
                           ('runtime_healthy', runtime.healthy_samples), ('runtime_window_sha256', window.hexdigest())]:
            equal(value, self.saved[key], key)

    def oracle(self):
        engine = GaitEngine(config=self.cfg)
        quality = self.quality(engine)
        engine.quality = quality
        quality.armed.connect(engine.begin_quality_session)
        quality.frame_ready.connect(engine.process_quality_frame)
        quality.frame_ready.connect(lambda *args: self.quality_tape.append((self.outer, args)))
        originals = {}
        depth = {'filter': 0, 'processor': 0}
        def wrap(cls, name, group, tape):
            original = getattr(cls, name)
            originals[(cls, name)] = original
            def call(obj, *args, **kwargs):
                top = depth[group] == 0
                depth[group] += 1
                try:
                    result = original(obj, *args, **kwargs)
                finally:
                    depth[group] -= 1
                if top:
                    tape.append((self.outer, name, args, kwargs, result if group == 'filter' else None))
                    if group == 'processor' and name == 'process':
                        f = args[0]
                        usable = np.frombuffer(f.contact_bits, dtype=np.uint8).copy()
                        usable[list(obj.device.bad_indices)] = 0
                        self.output_map.append((self.outer, f.sample_index, int(usable.sum())))
                return result
            setattr(cls, name, call)
        for method in ('feed', 'reset', 'flush'):
            wrap(GroundStabilityFilter, method, 'filter', self.filter_tape)
        for method in ('process', '_record_visual', 'summary', 'build_report', 'break_continuity'):
            wrap(WalkingProcessor, method, 'processor', self.processor_tape)
        time.perf_counter_ns = lambda: self.clock
        try:
            for i, frame in enumerate(self.frames):
                self.outer, self.clock = i, frame.received_monotonic_ns
                quality.on_frame(frame)
                if i == self.start - 1:
                    self.arm(quality)
                    self.context = quality.context
                if i >= self.start and (i - self.start + 1) % 1000 == 0:
                    self.states.append({'raw_sample': i, 'processor': state(engine.overground.processor),
                                        'filter_queue': len(engine.overground._frame_filter._queue)})
            self.terminal_poll(quality)
            quality.halt(); engine.overground.halt()
            report = asdict(engine.build_report(self.report['finish_reason']))
        finally:
            time.perf_counter_ns = REAL_CLOCK
            for (cls, name), original in originals.items():
                setattr(cls, name, original)
        # Exact data equality, with no timestamp/config/event field scrubbed.
        report.pop('export_frames'); report.pop('export_timestamps')
        equal(report, self.report, 'full report')
        self.check_quality(quality)
        processor = engine.overground.processor
        equal(processor.event_audit, self.saved['audit'], 'event audit')
        equal(processor.timeline, self.saved['timeline'], 'unmasked timeline')
        equal(engine.overground._frame_filter.mirror_guard.events, self.saved['mirror_events'], 'mirror history')
        archive = np.load(self.folder / 'raw_archive.npz')
        assert tuple(engine.overground.frames) == tuple(row.tobytes() for row in archive['bits'])
        assert np.array_equal(np.array(engine.overground.timestamps) - (processor.origin or 0), archive['device_timestamps'] - (processor.origin or 0))
        self.processor_report = self.processor_tape[-1]
        self.final_state = state(processor)
        self.report_hash = digest(report)
        del engine

    def measure(self, stage):
        """One timer pair per 1000 raw inputs, never per frame or nested call."""
        if stage == 'quality':
            obj = self.quality()
            emitted = []
            obj.frame_ready.connect(lambda *args: emitted.append(args))
            operations = [(i, 'on_frame', (f,), {}, None) for i, f in enumerate(self.frames)]
        elif stage == 'filter':
            obj = GroundStabilityFilter(self.context.layout, self.context.bad_indices)
            operations = self.filter_tape
        else:
            obj = WalkingProcessor(self.cfg, self.context)
            operations = self.processor_tape
        groups = {}
        for op in operations:
            block = -1 if op[0] < self.start else (op[0] - self.start) // 1000
            groups.setdefault(block, []).append(op)
        results, outputs = [], []
        time.perf_counter_ns = lambda: self.clock
        try:
            for block, ops in groups.items():
                wall, cpu = REAL_CLOCK(), time.thread_time_ns()
                for outer, name, args, kwargs, expected in ops:
                    self.clock = self.frames[outer].received_monotonic_ns
                    result = getattr(obj, name)(*args, **kwargs)
                    if stage == 'quality' and outer == self.start - 1:
                        self.arm(obj)
                    elif stage == 'filter':
                        outputs.append(result)
                cpu, wall = time.thread_time_ns() - cpu, REAL_CLOCK() - wall
                results.append({'block': block, 'raw_first': ops[0][0], 'raw_last': ops[-1][0],
                                'operations': len(ops), 'calls': dict(Counter(op[1] for op in ops)),
                                'thread_cpu_ns': cpu, 'wall_ns': wall})
        finally:
            time.perf_counter_ns = REAL_CLOCK
        if stage == 'quality':
            time.perf_counter_ns = lambda: self.clock
            try:
                self.terminal_poll(obj)
            finally:
                time.perf_counter_ns = REAL_CLOCK
            obj.halt(); self.check_quality(obj)
            assert emitted == [args for _, args in self.quality_tape], 'quality outputs'
        elif stage == 'filter':
            assert outputs == [op[4] for op in self.filter_tape], 'filter outputs'
            equal(obj.mirror_guard.events, self.saved['mirror_events'], 'filter mirror')
        else:
            equal(asdict(result)['walking_summary'], self.report['walking_summary'], 'processor full summary')
            equal(obj.timeline, self.saved['timeline'], 'processor timeline')
            equal(obj.event_audit, self.saved['audit'], 'processor audit')
            equal(state(obj), self.final_state, 'processor final state')
        return results


def main(args):
    app = QCoreApplication.instance() or QCoreApplication([])
    args.output.mkdir(parents=True, exist_ok=False)
    base = read(ROOT / 'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert all(file_sha(ROOT / name) == sha for name, sha in base.items()), 'baseline changed'
    trials, output = [], {'platform': platform.platform(), 'python': sys.version, 'numpy': np.__version__,
                          'source_base': '22f073f', 'baseline_files_verified': base,
                          'script_sha256': file_sha(Path(__file__)), 'trials': []}
    for name in args.cases:
        t = Trial(args.input / name / 'capture')
        t.oracle()
        item = {'case': name, 'inputs': t.manifest, 'strict_oracle_equal': True, 'report_sha256': t.report_hash,
                'formal_start': t.start, 'formal_end': t.end, 'states': t.states, 'final_state': t.final_state,
                'processor_call_counts': dict(Counter(op[1] for op in t.processor_tape)), 'repeats': []}
        np.save(args.output / (name + '_output_map.npy'), np.array(t.output_map, dtype=np.int64))
        output['trials'].append(item); trials.append(t)
        print('ORACLE PASS', name, item['processor_call_counts'], flush=True)
    # Interleaved cases and rotating stage order; no candidate or optimization A/B.
    for repeat in range(args.repeats):
        for j in range(len(trials)):
            index = (j + repeat) % len(trials)
            t, item = trials[index], output['trials'][index]
            stages = ['quality', 'filter', 'processor']
            stages = stages[repeat % 3:] + stages[:repeat % 3]
            record = {'repeat': repeat, 'order': stages, 'stages': {}}
            for stage in stages:
                record['stages'][stage] = t.measure(stage)
            item['repeats'].append(record)
            print('STAGES PASS', repeat, item['case'], flush=True)
    for t in trials:
        assert t.manifest == {name: file_sha(t.folder / name) for name in t.manifest}, 'input mutated'
    (args.output / 'compute.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, default=ROOT / 'experiments/single_usb_human_etw/runs')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--cases', nargs='+', choices=NAMES, default=NAMES)
    main(p.parse_args())
