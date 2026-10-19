import base64
import struct
import unittest
from review import verify_entry

class EntryChecks(unittest.TestCase):
    def event(self):
        b=bytearray(74);struct.pack_into('<Q',b,48,0x123456789)
        return dict(version=3,flags=0x40,payload=base64.b64encode(b).decode())
    def test_known_address(self):self.assertEqual(verify_entry(self.event(),0x123456789),0x123456789)
    def test_wrong_address(self):
        with self.assertRaises(ValueError):verify_entry(self.event(),0x123456788)
    def test_other_version(self):
        e=self.event();e['version']=4
        with self.assertRaises(ValueError):verify_entry(e,0x123456789)
    def test_other_width(self):
        e=self.event();e['flags']=0x20
        with self.assertRaises(ValueError):verify_entry(e,0x123456789)
    def test_ambiguous_bytes(self):
        e=self.event();b=bytearray(base64.b64decode(e['payload']));struct.pack_into('<Q',b,16,0x123456789);e['payload']=base64.b64encode(b).decode()
        with self.assertRaises(ValueError):verify_entry(e,0x123456789)
    def test_other_length(self):
        e=self.event();e['payload']=base64.b64encode(base64.b64decode(e['payload'])+b'\0\0').decode()
        with self.assertRaises(ValueError):verify_entry(e,0x123456789)
