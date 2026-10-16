"""Archived sensor payloads independently survive original parser/assembler."""
import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from hardware.sensor_frame import DeviceLayout,SensorSegment
from packet_source import PacketSource
HERE=Path(__file__).resolve().parent
for mode in ('walk','run'):
    original=json.loads((HERE/'inputs'/mode/'report.json').read_text())['report_config_snapshot']['device']
    g=original['layout'];layout=DeviceLayout(tuple(SensorSegment(**s) for s in g['segments']),tuple(g['invalid_bit_indices']))
    with np.load(HERE/'inputs'/mode/'raw_frames.npz') as raw:
        # Includes the whole original counter sequence, not just clear examples.
        data={k:raw[k].copy() for k in raw.files}
    parser=PacketSource(data,layout,original['stream_id'])
    for k,n in enumerate(data['sample_indices']):
        frame=parser.frame(k)
        assert frame.sample_index==int(n) and frame.frame_index==int(data['frame_indices'][k])
        assert frame.contact_bits==data['bits'][k].tobytes() and frame.wire_payload==data['wire'][k].tobytes()
        assert frame.valid_bits==data['valid_bits'][k].tobytes() and frame.dropped_frames_before==int(data['dropped_frames_before'][k])
    print(mode,'PASS',len(data['sample_indices']),'original frames through parser/assembler')
