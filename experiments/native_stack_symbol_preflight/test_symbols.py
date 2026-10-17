"""Guard against false acceptance/rejection in the symbol measurement layer."""
from pathlib import Path
import struct
import tempfile
import unittest
import uuid

from pe_identity import pdb
from readiness import pdb_matches

GUID = '00112233-4455-6677-8899-AABBCCDDEEFF'


def msf(info_age, dbi_age):
    size = 512
    data = bytearray(size * 5)
    data[:32] = b'Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0'
    struct.pack_into('<6I',data,32,size,1,5,28,0,1)
    struct.pack_into('<I',data,size,2)
    struct.pack_into('<7I',data,size*2,4,0,28,0,64,3,4)
    struct.pack_into('<III',data,size*3,20000404,1234,info_age)
    data[size*3+12:size*3+28] = uuid.UUID(GUID).bytes_le
    struct.pack_into('<iII',data,size*4,-1,19990903,dbi_age)
    return data


class IdentityTests(unittest.TestCase):
    def read(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'any-name.pdb'
            path.write_bytes(data)
            return pdb(path)

    def test_rewritten_info_age_uses_dbi_age(self):
        identity = self.read(msf(4,1))
        self.assertEqual(identity['info_age'],4)
        self.assertEqual(identity['age'],1)
        self.assertTrue(pdb_matches({'guid':GUID,'age':1},identity))

    def test_same_guid_wrong_dbi_age_rejected(self):
        identity = self.read(msf(4,2))
        self.assertFalse(pdb_matches({'guid':GUID,'age':1},identity))

    def test_same_age_wrong_guid_rejected(self):
        identity = self.read(msf(1,1))
        self.assertFalse(pdb_matches({'guid':str(uuid.UUID(int=0)),'age':1},identity))

    def test_not_a_pdb_rejected(self):
        with self.assertRaises(AssertionError):
            self.read(b'not a symbol file')


if __name__=='__main__':
    unittest.main()
