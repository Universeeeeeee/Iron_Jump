"""Reuse the admitted same-event join; add wire validation and bounded claims."""
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
folder = Path(sys.argv[1])
subprocess.run([sys.executable, str(HERE.parent / 'measurement_boundary_replay_20261022/analyze.py'), str(folder)], check=True)
result = json.loads((folder / 'analysis.json').read_text())
for case in result['cases']:
    wires = list((folder / case['case']).glob('wire_*.json'))
    case['wire'] = [json.loads(p.read_text()) for p in wires]
    if 'segmented' in case['case']:
        assert len(wires) == 1
        wire = case['wire'][0]
        assert not wire['errors'] and not wire['parser_errors']
        assert wire['verified_frames'] > 11000
        case['shape'] = 'segmented'
    else:
        assert not wires
        case['shape'] = 'decoded'
result['limits'] = [
    'Wire controls reconstruct packet bytes from retained decoded payloads. Segment packetization, fixed 2048-byte reads and 20ms timing are synthetic, not original USB traffic.',
    'Native DLL/device, camera, MediaPipe and SDK are absent. Offscreen paintEvent completion is not DWM presentation.',
    'Decoded and wire controls include different verification work. One run per case is not a calibrated perturbation or statistical performance comparison.',
    'Source reader thread CPU includes parser, assembler, synchronous signal delivery and verification, not pure protocol cost; no GIL/CPU percentages are inferred.',
    'Signed nominal phase offsets follow chunk-start pacing and are not causal waits. Actual same-event stages retain the original causality gates.',
]
(folder / 'analysis.json').write_text(json.dumps(result, indent=2) + '\n')
