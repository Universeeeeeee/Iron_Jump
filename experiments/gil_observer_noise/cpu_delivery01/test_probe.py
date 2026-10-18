import struct
import unittest
from cpu_probe import parse_sets


class CpuSetParserChecks(unittest.TestCase):
    def fixture(self):
        b=bytearray(32);struct.pack_into('<IIIH',b,0,32,0,55,2);b[14]=7;b[15]=3;b[18]=9
        return bytes(b),[32,8,12,14,15,18]
    def test_uses_sdk_supplied_offsets(self):
        rows=parse_sets(*self.fixture());self.assertEqual((rows[0]['group'],rows[0]['logical'],rows[0]['core'],rows[0]['efficiency_class']),(2,7,3,9))
    def test_unknown_record_keeps_raw_bytes(self):
        b,l=self.fixture();b=bytearray(b);struct.pack_into('<I',b,4,99);v=parse_sets(bytes(b),l);self.assertEqual(v[0]['type'],99);self.assertEqual(v[0]['raw_hex'],bytes(b).hex())
    def test_bad_length_rejected(self):
        b,l=self.fixture()
        with self.assertRaises(ValueError):parse_sets(b[:-1],l)
    def test_offset_outside_record_rejected(self):
        b,l=self.fixture();l[-1]=40
        with self.assertRaises(ValueError):parse_sets(b,l)
    def test_short_header_rejected(self):
        with self.assertRaises(ValueError):parse_sets(b'abc',[32,8,12,14,15,18])
    def test_zero_size_rejected(self):
        with self.assertRaises(ValueError):parse_sets(b'\0'*32,[32,8,12,14,15,18])


if __name__=='__main__':unittest.main()
