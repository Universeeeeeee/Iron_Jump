"""Exercise E1a in the actual assembler, preserving all packet/counter logic."""
from dataclasses import asdict
import inspect
import json
from types import SimpleNamespace
import traceback

from experiment import *
import hardware.sensor_frame as source_module


def main():
    source = inspect.getsource(source_module.SensorFrameAssembler)
    old = '        self._last_payload = None\n'
    assert source.count(old) == 1
    source = source.replace(old, old+'        self._last_contact_bits = None\n')
    old = '        self._last_index, self._last_payload = index, payload\n'
    assert source.count(old) == 1
    source = source.replace(old, '        contact_bits = (self._last_contact_bits if payload == self._last_payload\n'
                           '                        else self.layout.contact_bits(payload))\n'
                           '        self._last_contact_bits = contact_bits\n'+old)
    old = '            self.layout.contact_bits(payload), self.valid_bits, payload, dropped, tuple(flags),\n'
    assert source.count(old) == 1
    source = source.replace(old, '            contact_bits, self.valid_bits, payload, dropped, tuple(flags),\n')
    (HERE/'assembler_candidate_source.py').write_text(source)
    namespace = dict(vars(source_module))
    exec(compile(source, str(HERE/'assembler_candidate_source.py'), 'exec'), namespace)
    candidate_cls = namespace['SensorFrameAssembler']
    rows = []
    for modules in (1, 3, 8):
        for custom in (False, True):
            layout, frames = synthetic('edges', 2100, modules, custom)
            for multipart in (False, True):
                if modules == 1 and multipart:
                    continue
                a, b = source_module.SensorFrameAssembler(layout), candidate_cls(layout)
                a.stream_id = b.stream_id = 'assembler'
                deliveries = 0
                for k, f in enumerate(frames):
                    if k == 1000:
                        a.reset(); b.reset(); a.stream_id = b.stream_id = 'reset'
                    payloads = ([f.wire_payload[i:i+12] for i in range(0, layout.payload_bytes, 12)]
                                if multipart else [f.wire_payload])
                    for i, payload in enumerate(payloads):
                        packet = SimpleNamespace(frameIdx=f.frame_index, packNum=modules if multipart else 1,
                                                 packIdx=i, buffer=payload)
                        x, y = a.feed(packet, f.received_monotonic_ns), b.feed(packet, f.received_monotonic_ns)
                        assert x == y, (modules, custom, multipart, k)
                        assert a.pop_issues() == b.pop_issues()
                        deliveries += x is not None
                    if k % 200 == 0:
                        # Exact duplicate, conflicting duplicate and late packet.
                        for frame_index, raw in ((f.frame_index,payloads[0]),
                                                (f.frame_index,bytes([payloads[0][0]^1])+payloads[0][1:]),
                                                (max(0,f.frame_index-1),payloads[0])):
                            packet = SimpleNamespace(frameIdx=frame_index,packNum=modules if multipart else 1,
                                                     packIdx=0,buffer=raw)
                            assert a.feed(packet,f.received_monotonic_ns) == b.feed(packet,f.received_monotonic_ns)
                            assert a.pop_issues() == b.pop_issues()
                rows.append({'modules':modules,'custom':custom,'multipart':multipart,
                             'source_frames':len(frames),'delivered_frames':deliveries,'exact':True})
    dump(HERE/'assembler_checks.json',{'results':rows,'source_sha256':
         hashlib.sha256(source.encode()).hexdigest(),'all_exact':True})
    print(json.dumps({'cases':len(rows),'all_exact':True}),flush=True)


if __name__=='__main__':
    try:
        main()
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
