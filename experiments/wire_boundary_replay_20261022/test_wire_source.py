"""Validate the diagnostic encoder against the independent production decoder."""
import unittest

from hardware.protocol import protocol_parser
from hardware.sensor_frame import DeviceLayout, SensorFrameAssembler
from wire_source import packets


class WireControlTests(unittest.TestCase):
    def test_complete_and_segmented_split_reads_decode_identically(self):
        layout = DeviceLayout.linear(8)
        payload = bytes(range(96))
        for segmented in (False, True):
            for read_size in (1, 17, 2048):
                with self.subTest(segmented=segmented, read_size=read_size):
                    wire = packets(53660, payload, segmented)
                    assembler = SensorFrameAssembler(layout)
                    buffer = bytearray()
                    frames = []
                    errors = []
                    for offset in range(0, len(wire), read_size):
                        buffer.extend(wire[offset:offset + read_size])
                        while True:
                            result = protocol_parser(buffer, on_error=errors.append)
                            if result[0] != 0:
                                break
                            frame = assembler.feed(result[3], 1)
                            if frame:
                                frames.append(frame)
                    self.assertFalse(buffer)
                    self.assertFalse(errors)
                    self.assertFalse(assembler.pop_issues())
                    self.assertEqual(len(frames), 1)
                    self.assertEqual(frames[0].frame_index, 53660)
                    self.assertEqual(frames[0].wire_payload, payload)
                    self.assertEqual(frames[0].contact_bits, layout.contact_bits(payload))

    def test_corrupt_crc_does_not_deliver_frame(self):
        wire = bytearray(packets(53660, bytes(range(96)), False))
        wire[-5] ^= 1
        errors = []
        self.assertNotEqual(protocol_parser(wire, on_error=errors.append)[0], 0)
        self.assertIn('checksum_or_tail_error', errors)


if __name__ == '__main__':
    unittest.main()
