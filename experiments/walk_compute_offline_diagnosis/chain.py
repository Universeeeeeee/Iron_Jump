"""Coarse original full-chain replay to check stage-tape scope limitations."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
import platform
import sys

from replay import (Trial, NAMES, ROOT, REAL_CLOCK, file_sha, read, equal,
                    GaitEngine, QCoreApplication)


if sys.platform == 'win32':
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentThread.restype = ctypes.c_void_p
    kernel.QueryThreadCycleTime.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong)]
    def cycles():
        value = ctypes.c_ulonglong()
        if not kernel.QueryThreadCycleTime(kernel.GetCurrentThread(), ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.value
else:
    def cycles():
        return 0


def measure(t):
    engine = GaitEngine(config=t.cfg)
    quality = t.quality(engine)
    engine.quality = quality
    quality.armed.connect(engine.begin_quality_session)
    quality.frame_ready.connect(engine.process_quality_frame)
    rows = []
    time.perf_counter_ns = lambda: t.clock
    try:
        # Same preconstructed inputs, no call tapes or method wrappers.
        # Preflight is one separate block; formal boundaries are 1000 frames.
        ranges = [(-1, 0, t.start)] + [(i // 1000, t.start + i, min(t.start + i + 1000, t.end))
                                      for i in range(0, t.end - t.start, 1000)]
        for block, first, stop in ranges:
            cycle_start = cycles()
            wall, cpu = REAL_CLOCK(), time.thread_time_ns()
            for i in range(first, stop):
                frame = t.frames[i]
                t.clock = frame.received_monotonic_ns
                quality.on_frame(frame)
                if i == t.start - 1:
                    t.arm(quality)
            cpu, wall = time.thread_time_ns() - cpu, REAL_CLOCK() - wall
            cycle_count = cycles() - cycle_start
            rows.append({'thread_cycles': cycle_count, 'block': block, 'raw_first': first, 'raw_last': stop - 1,
                         'thread_cpu_ns': cpu, 'wall_ns': wall})
        # Stop/report is explicit, separate from sample-processing costs.
        wall, cpu = REAL_CLOCK(), time.thread_time_ns()
        t.terminal_poll(quality)
        quality.halt(); engine.overground.halt()
        report = engine.build_report(t.report['finish_reason'])
        terminal = {'thread_cpu_ns': time.thread_time_ns() - cpu, 'wall_ns': REAL_CLOCK() - wall}
    finally:
        time.perf_counter_ns = REAL_CLOCK
    replay = asdict(report)
    replay.pop('export_frames'); replay.pop('export_timestamps')
    equal(replay, t.report, 'full chain report')
    t.check_quality(quality)
    equal(engine.overground.processor.event_audit, t.saved['audit'], 'chain audit')
    equal(engine.overground.processor.timeline, t.saved['timeline'], 'chain timeline')
    return {'blocks': rows, 'terminal': terminal, 'report_and_quality_exact': True}


def main(args):
    app = QCoreApplication.instance() or QCoreApplication([])
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = read(ROOT / 'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert all(file_sha(ROOT / path) == sha for path, sha in baseline.items())
    trials = [Trial(args.input / name / 'capture') for name in NAMES]
    output = {'platform': platform.platform(), 'python': sys.version, 'thread_clock': vars(time.get_clock_info('thread_time')), 'cycle_note': 'Raw QueryThreadCycleTime counts; not instructions or seconds, not converted using guessed CPU frequency.', 'script_sha256': file_sha(Path(__file__)), 'replay_script_sha256': file_sha(Path(__file__).with_name('replay.py')),
              'trials': [{'case': name, 'inputs': t.manifest, 'repeats': []} for name, t in zip(NAMES, trials)]}
    for repeat in range(args.repeats):
        for j in range(4):
            index = (j + repeat) % 4
            result = measure(trials[index])
            output['trials'][index]['repeats'].append(result)
            print('CHAIN PASS', repeat, NAMES[index], flush=True)
    for t in trials:
        assert t.manifest == {name: file_sha(t.folder / name) for name in t.manifest}
    (args.output / 'chain.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, default=ROOT / 'experiments/single_usb_human_etw/runs')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--repeats', type=int, default=3)
    main(p.parse_args())
