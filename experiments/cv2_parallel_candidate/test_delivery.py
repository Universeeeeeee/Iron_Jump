import base64
import struct
import unittest
from delivery import gate,classify_starts

class DeliveryTests(unittest.TestCase):
    def valid(self):return dict(cv2_starts=[{'tid':1}],unknown=[]),dict(cv2_starts=[],unknown=[]),[{'sha':'a'}],[{'sha':'a'}],1
    def test_positive(self):self.assertTrue(all(gate(*self.valid()).values()))
    def test_getter_without_delivery_insufficient(self):
        a,b,x,y,n=self.valid();b['cv2_starts']=[{'tid':2}];self.assertFalse(all(gate(a,b,x,y,n).values()))
    def test_missing_baseline_insufficient(self):
        a,b,x,y,n=self.valid();a['cv2_starts']=[];self.assertFalse(all(gate(a,b,x,y,n).values()))
    def test_pixel_change_rejects(self):
        a,b,x,y,n=self.valid();y=[{'sha':'b'}];self.assertFalse(all(gate(a,b,x,y,n).values()))
    def test_unknown_layout_rejects_gate(self):
        a,b,x,y,n=self.valid();b['unknown']=[{}];self.assertFalse(all(gate(a,b,x,y,n).values()))
    def events(self):
        d=bytearray(56);struct.pack_into('<QQII',d,0,4096,4096,7,33);d+=('C:\\cv2.pyd\0').encode('utf-16le')
        e=bytearray(74);struct.pack_into('<II',e,0,7,9);struct.pack_into('<Q',e,48,4160)
        return [dict(provider='2cb15d1d-x',opcode=10,version=3,flags=64,qpc=0,payload=base64.b64encode(d).decode()),dict(provider='3d6fa8d1-x',opcode=1,version=3,flags=64,qpc=50,payload=base64.b64encode(e).decode())]
    def test_map_known_layout(self):
        r=classify_starts(self.events(),7,10,100,10**9,0,0,dict(image_size=4096,checksum=33));self.assertEqual(r['cv2_starts'][0]['rva'],64);self.assertFalse(r['unknown'])
    def test_other_version_not_silently_counted_absent(self):
        e=self.events();e[1]['version']=4;r=classify_starts(e,7,10,100,10**9,0,0,dict(image_size=4096,checksum=33));self.assertTrue(r['unknown'])
    def test_boundary_ambiguity_retained(self):
        r=classify_starts(self.events(),7,50,100,10**9,-1,1,dict(image_size=4096,checksum=33));self.assertTrue(r['unknown'])
