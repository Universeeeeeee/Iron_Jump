"""Restore original parser/assembler work using captured payloads.

Envelopes use the single-packet 96-byte DATA_REPORT format independently captured
on 2026-09-29 (tests/test_sensor_interface.py), not a claimed recording of the
2026-10-15 USB packet boundaries. No USB bus/DLL-read workload is simulated.
"""
import time
from hardware.protocol import protocol_parser,crc8_poly_07,E_DATA_REPORT
from hardware.sensor_frame import SensorFrameAssembler

class PacketSource:
    def __init__(self,data,layout,stream_id):
        self.assembler=SensorFrameAssembler(layout)
        self.assembler.stream_id=stream_id
        self.assembler._sample_index=int(data['sample_indices'][0])
        self.packets=[]
        for index,wire in zip(data['frame_indices'],data['wire']):
            payload=int(index).to_bytes(4,'little')+bytes((1,0))+wire.tobytes()
            body=bytes((E_DATA_REPORT,))+len(payload).to_bytes(2,'little')+payload
            self.packets.append(b'\x5a'*4+body+bytes((crc8_poly_07(body),))+b'\xa5'*4)
    def frame(self,k):
        buffer=bytearray(self.packets[k]);ret,kind,_,part,_=protocol_parser(buffer)
        assert ret==0 and kind==E_DATA_REPORT and not buffer
        frame=self.assembler.feed(part,time.perf_counter_ns())
        assert frame is not None and not self.assembler.pop_issues()
        return frame
