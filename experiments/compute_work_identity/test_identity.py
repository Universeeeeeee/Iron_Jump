from dataclasses import dataclass
import unittest
from run import canonical

class Identity(unittest.TestCase):
    def test_bytes_preserved(self):self.assertNotEqual(canonical(b'\0'),canonical(b'\1'))
    def test_sequence_type_preserved(self):self.assertNotEqual(canonical([1]),canonical((1,)))
    def test_snapshot_owned(self):
        @dataclass
        class Packet: values:list
        x=Packet([1]);a=canonical(x);x.values.append(2);self.assertNotEqual(a,canonical(x))
    def test_unknown_type_rejected(self):
        with self.assertRaises(TypeError):canonical(object())

if __name__=='__main__':unittest.main()
