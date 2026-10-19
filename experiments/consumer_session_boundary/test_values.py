"""Offline value-boundary checks, not an IPC or throughput qualification."""
import json
from pathlib import Path
import pickle
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from hardware.sensor_frame import DeviceLayout,SensorFrame,AcquisitionIssue

class Values(unittest.TestCase):
    def roundtrip(self,value):return pickle.loads(pickle.dumps(value,protocol=5))
    def test_bad_beam_keeps_physical_coordinate_and_wire_order(self):
        base=DeviceLayout.linear(8,wire_order=(8,7,6,5,4,3,2,1))
        layout=DeviceLayout(base.segments,(576,))
        bits=bytearray(768);bits[575]=bits[576]=bits[577]=1
        valid=bytearray([1])*768;valid[576]=0
        frame=SensorFrame('stream',layout,12,1002,123456789,bytes(bits),bytes(valid),bytes(96),3,('frame_gap',))
        restored=self.roundtrip(frame)
        self.assertEqual(restored,frame);self.assertEqual(len(restored.contact_bits),768)
        self.assertEqual(restored.layout.invalid_bit_indices,(576,));self.assertEqual(restored.layout.positions_m,layout.positions_m)
        self.assertEqual(restored.layout.positions_m[576],6.)
        self.assertGreater(restored.layout.positions_m[577],6.)
        self.assertEqual(restored.layout.segments[0].wire_index,7)
        self.assertEqual(restored.valid_bits[576],0)
    def test_gaps_and_stream_identity_are_not_renumbered(self):
        layout=DeviceLayout.linear()
        frames=[SensorFrame(stream,layout,index,sample,900000000+sample,bytes(96),bytes([1])*96,bytes(12),dropped,()) for stream,index,sample,dropped in [('first',1,100,0),('first',4,103,2),('second',0,0,0)]]
        self.assertEqual(self.roundtrip(frames),frames)
        self.assertEqual([f.sample_index for f in self.roundtrip(frames)],[100,103,0])
    def test_issue_position_preserved(self):
        issue=AcquisitionIssue('missing_segment',123,(2,5));self.assertEqual(self.roundtrip(issue),issue)
    def test_publication_value_is_detached(self):
        value=dict(feet=[dict(contact_id=1,position_m=6.1)],positions_m=(6.,6.1),valid_bits=[0,1],contact_bits=[1,1])
        copy=self.roundtrip(value);copy['feet'][0]['position_m']=100;copy['valid_bits'][0]=1
        self.assertEqual(value['feet'][0]['position_m'],6.1);self.assertEqual(value['valid_bits'][0],0)
    def test_existing_full_report_value_preserved(self):
        path=ROOT/'experiments/gui_qos_candidate/runs/evidence01/runs/gui02/pair01_default/capture/report.json'
        if not path.exists():self.skipTest('Retained report archive unavailable; record missing coverage')
        report=json.loads(path.read_text(encoding='utf-8-sig'));copy=self.roundtrip(report)
        self.assertEqual(copy,report)
        self.assertEqual(json.dumps(copy,sort_keys=True),json.dumps(report,sort_keys=True))
