"""Independent unwrapped synchronous production replay; never times performance."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from qtpy.QtCore import QCoreApplication
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.gait_engine import GaitEngine
from engine.device_quality_session import DeviceQualitySession
from hardware.beam_quality import BeamQualityPolicy
from hardware.sensor_frame import DeviceLayout, SensorSegment, SensorFrame


def canonical(report):
    for branch in (report['report_config_snapshot']['device'],
                   report['report_config_snapshot']['beam_quality']['preflight']):
        del branch['checked_monotonic_ns']
    return report


def main(folder, mode, output):
    app = QCoreApplication([])
    meta = json.loads((folder / 'report.json').read_text(encoding='utf-8'))['report_config_snapshot']
    device = meta['device']
    layout = DeviceLayout(tuple(SensorSegment(**v) for v in device['layout']['segments']),
                          tuple(device['layout']['invalid_bit_indices']))
    cls = WalkingConfig if mode == 'walk' else OvergroundRunningConfig
    cfg = cls(**{k: v for k, v in meta.items() if k in cls.__dataclass_fields__ and cls.__dataclass_fields__[k].init})
    engine = GaitEngine(config=cfg)
    quality = DeviceQualitySession(cfg, BeamQualityPolicy(), engine)
    engine.quality = quality
    quality.armed.connect(engine.begin_quality_session)
    quality.frame_ready.connect(engine.process_quality_frame)
    last = max(r['touch_sample'] for r in json.loads((folder / 'timing.json').read_text(encoding='utf-8'))['rows']) + 1200
    with np.load(folder / 'raw_frames.npz') as raw:
        mask = (raw['sample_indices'] >= device['checked_sample_index'] - 3500) & (raw['sample_indices'] <= last)
        indices = np.flatnonzero(mask)
        data = {key: raw[key][indices] for key in ('sample_indices', 'frame_indices', 'received_ns', 'bits', 'wire')}
        for index, n in enumerate(data['sample_indices']):
            n = int(n)
            frame = SensorFrame(device['stream_id'], layout, int(data['frame_indices'][index]), n,
                                time.perf_counter_ns(),
                                data['bits'][index].tobytes(), b'\x01' * layout.bit_count,
                                data['wire'][index].tobytes())
            quality.on_frame(frame)
            if n == device['checked_sample_index']:
                quality.arm_checked((quality._status()['device_key'], True))
                assert quality.context is not None
    quality.halt()
    engine.overground.halt()
    report = asdict(engine.build_report('manual'))
    report.pop('export_frames')
    report.pop('export_timestamps')
    canonical(report)
    runtime = quality._runtime
    window = hashlib.sha256()
    for bits, changes in runtime._window:
        window.update(bits.tobytes())
        window.update(changes.tobytes())
    output.mkdir(parents=True, exist_ok=False)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    (output / 'runtime.json').write_text(json.dumps({
        'counts': runtime._counts.tolist(), 'transitions': runtime._transitions.tolist(),
        'healthy_samples': runtime.healthy_samples, 'window_sha256': window.hexdigest(),
    }), encoding='utf-8')
    print(mode, 'oracle', len(indices), 'frames', report['touch_count'], 'touches', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--mode', choices=('walk', 'run'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.input, args.mode, args.output)
