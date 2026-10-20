import base64
import json
from pathlib import Path
import struct
import tempfile
import unittest
from check_schema import check,PERF
class MSI(unittest.TestCase):
    def fixture(self,root,message=4,routine='0x1234',time_shift=0):
        (root/'decoded01').mkdir()
        data=struct.pack('<qQBBHI',100,0x1234,1,145,0,4)
        (root/'decoded01/events.jsonl').write_text(json.dumps(dict(provider=PERF,opcode=50,version=2,cpu=0,payload=base64.b64encode(data).decode()))+'\n')
        (root/'target01.json').write_text(json.dumps(dict(before=dict(before=dict(frequency=10000000,filetime_100ns=1000000000,qpc_before=0,qpc_after=0)))))
        xml=f'''<Events><Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System><Opcode>50</Opcode><Execution ProcessorID="0"/><TimeCreated SystemTime="2026-10-20T00:00:00+08:00"/></System><EventData><Data Name="InitialTime">{1000000100+time_shift}</Data><Data Name="Routine">{routine}</Data><Data Name="ReturnValue">1</Data><Data Name="Vector">145</Data><Data Name="Reserved">0</Data><Data Name="MessageNumber">{message}</Data></EventData><RenderingInfo><Opcode>ISR-MSI</Opcode></RenderingInfo><ExtendedTracingInfo xmlns="http://schemas.microsoft.com/win/2004/08/events/trace"><EventGuid>{{{PERF}}}</EventGuid></ExtendedTracingInfo></Event></Events>'''
        (root/'schema01.xml').write_text(xml)
    def test_MSI_extra_message_is_verified(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);self.fixture(r);self.assertTrue(check(r)['all_DPC_ISR_events_match_independent_TDH_fields'])
    def test_incorrect_extra_message_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);self.fixture(r,message=5)
            with self.assertRaises(AssertionError):check(r)
    def test_clock_mismatch_not_reinterpreted(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);self.fixture(r,time_shift=20000)
            with self.assertRaises(AssertionError):check(r)
if __name__=='__main__':unittest.main()
