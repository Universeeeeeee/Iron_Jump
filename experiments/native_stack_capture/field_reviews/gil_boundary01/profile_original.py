"""Locate NumPy public C calls in selected original, device-free replay batches.

No performance measurements or implementation alternatives are compared.
"""
import argparse
from collections import Counter
import ctypes as C
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(args):
    args.output.mkdir(exist_ok=False)
    helper = args.helper_root / 'experiments/walk_compute_offline_diagnosis/replay.py'
    spec = importlib.util.spec_from_file_location('original_replay', helper)
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    frozen_path = args.field_root / 'experiments/single_usb_human_etw/frozen_sources.json'
    frozen = r.read(frozen_path)
    assert sha(frozen_path) == 'e81e6a013c1feef532124204ff77768f33ac9adeb8512f7bf4490a28f4017aa0'
    preserved = {args.field_root / name: digest for name, digest in frozen['files'].items()}
    # Imported application copies must be byte-identical to the field sources.
    for module in list(sys.modules.values()):
        file = getattr(module, '__file__', None)
        if not file:
            continue
        path = Path(file).resolve()
        try:
            rel = path.relative_to(args.helper_root.resolve())
        except ValueError:
            continue
        if path == helper.resolve():
            continue
        field = args.field_root / rel
        assert field.is_file() and sha(path) == sha(field), str(rel)
        preserved[path] = preserved[field] = sha(path)
    assert all(sha(path) == digest for path, digest in preserved.items())
    pyd = Path(np._core._multiarray_umath.__file__)
    assert sha(pyd) == '4fb4c5d62a6bd766eea716350eaf5396580e33cf7dc159e305488d1b7d72dad2'
    app = r.QCoreApplication.instance() or r.QCoreApplication([])
    folder = args.field_root / 'experiments/single_usb_human_etw/runs/20261017_214905_5c874d97_walk_off/capture'
    t = r.Trial(folder)
    engine = r.GaitEngine(config=t.cfg)
    quality = t.quality(engine)
    engine.quality = quality
    quality.armed.connect(engine.begin_quality_session)
    quality.frame_ready.connect(engine.process_quality_frame)
    batches = [(t.start + 1000, t.start + 1019), (31968, 31987),
               (32368, 32387), (32568, 32587), (32668, 32687)]
    calls = Counter()
    active = None

    def profile(frame, event, value):
        if event != 'c_call' or getattr(value, '__qualname__', '') not in ('ufunc.reduce', 'ndarray.all'):
            return
        obj = value.__self__
        owner = obj.__name__ if isinstance(obj, np.ufunc) else 'ndarray'
        arrays = []
        if isinstance(obj, np.ndarray):
            arrays.append(('self', obj.shape, str(obj.dtype)))
        arrays += [(name, v.shape, str(v.dtype)) for name, v in frame.f_locals.items()
                   if isinstance(v, np.ndarray)]
        stack = []
        cursor = frame
        while cursor:
            path = Path(cursor.f_code.co_filename)
            for root, label in [(args.helper_root, 'app'), (Path(np.__file__).parent, 'numpy')]:
                try:
                    name = str(path.relative_to(root)).replace('\\', '/')
                except ValueError:
                    continue
                stack.append((label, name, cursor.f_code.co_name, cursor.f_lineno))
                break
            cursor = cursor.f_back
        calls[active, value.__qualname__, owner, tuple(arrays), tuple(stack)] += 1

    real_clock = time.perf_counter_ns
    time.perf_counter_ns = lambda: t.clock
    try:
        for i, frame in enumerate(t.frames):
            active = next((batch for batch in batches if batch[0] <= i <= batch[1]), None)
            sys.setprofile(profile if active else None)
            t.clock = frame.received_monotonic_ns
            quality.on_frame(frame)
            if i == t.start - 1:
                t.arm(quality)
        sys.setprofile(None)
        t.terminal_poll(quality)
        quality.halt()
        engine.overground.halt()
        report = asdict(engine.build_report(t.report['finish_reason']))
    finally:
        sys.setprofile(None)
        time.perf_counter_ns = real_clock
    report.pop('export_frames')
    report.pop('export_timestamps')
    r.equal(report, t.report, 'full original report')
    t.check_quality(quality)
    r.equal(engine.overground.processor.event_audit, t.saved['audit'], 'event audit')
    r.equal(engine.overground.processor.timeline, t.saved['timeline'], 'timeline')
    assert all(sha(path) == digest for path, digest in preserved.items())
    assert t.manifest == {name: sha(folder / name) for name in t.manifest}
    result = dict(case=folder.parent.name, profiled_batches=batches,
        calls=[dict(batch=key[0], entry=key[1], owner=key[2], arrays=key[3], stack=key[4], count=count)
               for key, count in calls.items()],
        full_report_quality_audit_timeline_exact=True, input_sha256=t.manifest,
        source_sha256={str(p): d for p, d in preserved.items()},
        helper_sha256=sha(helper), script_sha256=sha(Path(__file__)), numpy_sha256=sha(pyd),
        limits=['Single-thread original replay identifies possible original caller paths, not the live waiting call at a particular native timestamp.',
                'Profiling is intrusive and records no elapsed time. Counts are not GIL wait counts, durations or field CPU shares.',
                'Only two public C entry families are profiled; other Python/NumPy/Qt operations are not excluded. No device, camera, trace or GUI started.'])
    with (args.output / 'result.json').open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print('Exact report, quality, audit and timeline; public NumPy caller paths:', len(calls), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--field-root', type=Path, required=True)
    parser.add_argument('--helper-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
