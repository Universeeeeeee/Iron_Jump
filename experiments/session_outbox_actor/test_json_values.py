import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from hardware.sensor_frame import DeviceLayout
from json_values import json_value

class EvidenceEncoding(unittest.TestCase):
    def test_actual_start_key_can_be_written_without_changing_live_value(self):
        layout=DeviceLayout.linear(8,wire_order=(8,7,6,5,4,3,2,1))
        command=dict(sequence=2,kind='start',quality_key=('stream',layout,(576,)))
        restored=json.loads(json.dumps(dict(commands=[command],complete=True),default=json_value))
        encoded=restored['commands'][0]['quality_key'][1]
        self.assertEqual(encoded['value_type'],'hardware.sensor_frame.DeviceLayout')
        self.assertEqual(encoded['fields']['segments'][0]['wire_index'],7)
        self.assertIs(command['quality_key'][1],layout)
        self.assertTrue(restored['complete'])
    def test_unknown_objects_not_silently_stringified(self):
        with self.assertRaises(TypeError):json.dumps(dict(value=object()),default=json_value)
