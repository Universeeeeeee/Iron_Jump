import unittest
from dataclasses import dataclass
from actor import json_value


@dataclass(frozen=True)
class Segment:
 segment_id:str


@dataclass(frozen=True)
class Layout:
 segments:tuple


class ReadinessEvidenceTests(unittest.TestCase):
 def test_nested_device_layout_is_json_serializable(self):
  value=json_value(dict(ready=False,effective_layout=Layout((Segment('1'),Segment('2')))))
  self.assertEqual([item['segment_id'] for item in value['effective_layout']['segments']],['1','2'])


if __name__=='__main__':unittest.main()
