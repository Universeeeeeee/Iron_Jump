"""Isolated arithmetic/window/quality-mask timing; never used as GUI acceptance."""
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]), str(HERE)]
import numpy as np
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.beam_quality import BeamQualityPolicy
from hardware.walking_preflight import RuntimeBeamEvidence
from fused_runtime import runtime_class, warmup


def run(variant, frames):
    policy = BeamQualityPolicy()
    runtime = RuntimeBeamEvidence(policy) if variant == 'A' else runtime_class(variant)(policy)
    previous_mask = None
    indices = ()
    started = time.perf_counter()
    for frame in frames:
        runtime.observe(frame)
        if runtime.healthy_samples < policy.samples:
            previous_mask, indices = None, ()
        else:
            if variant == 'A':
                mask = (runtime._counts >= policy.samples * .95) | (runtime._transitions >= 20)
                changed = not np.array_equal(mask, previous_mask)
            else:
                mask, changed = runtime.suspicious_mask, runtime.mask_changed
            if changed:
                previous_mask = mask
                indices = tuple(np.flatnonzero(mask).tolist())
    elapsed = time.perf_counter() - started
    state = hashlib.sha256(runtime._counts.tobytes() + runtime._transitions.tobytes()).hexdigest()
    return {'seconds': elapsed, 'frames_per_second': len(frames) / elapsed,
            'microseconds_per_frame': elapsed * 1e6 / len(frames), 'state_sha256': state,
            'suspicious_indices': indices}


if __name__ == '__main__':
    warmup()
    result = {'platform': platform.platform(), 'python': sys.version, 'numpy': np.__version__,
              'scope': 'isolated runtime and adjacent mask, no Qt/vision/competing thread', 'runs': []}
    for modules in (1, 2, 4, 8):
        layout = DeviceLayout.linear(modules)
        clear = bytes(layout.bit_count)
        active = b'\1' + clear[1:]
        frames = [SensorFrame('benchmark', layout, n, n, n * 1000000,
                              active if n % 2 else clear, b'\1' * layout.bit_count,
                              (b'\xfe' + b'\xff' * (layout.payload_bytes - 1)) if n % 2
                              else b'\xff' * layout.payload_bytes) for n in range(12000)]
        for sequence in ('ABC', 'CBA', 'BAC'):
            states = []
            for variant in sequence:
                measurement = run(variant, frames)
                states.append(measurement['state_sha256'])
                result['runs'].append({'modules': modules, 'variant': variant, **measurement})
            assert len(set(states)) == 1
    (HERE / ('benchmark_' + sys.platform + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    print('Isolated benchmark complete; GUI acceptance is separate', flush=True)
