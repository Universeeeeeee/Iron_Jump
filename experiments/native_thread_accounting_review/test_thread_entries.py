import base64
import copy
import json
from pathlib import Path
import struct
import unittest
from thread_entry_review import decode, layout, module_at


class ThreadEntries(unittest.TestCase):
    def schema(self):
        return json.loads((Path(__file__).parent/'thread_start_schema01.json').read_text())['schema']

    def test_pointer_offsets_follow_native_schema(self):
        spec = layout(self.schema())
        values = [11948, 42, 1, 2, 3, 4, 255, 0x123456789abc, 0x100000001, 0, 8, 5, 2, 0]
        event = dict(provider='3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c', version=3, opcode=3, flags=0x40,
            payload=base64.b64encode(struct.pack(spec[0], *values)+b'\x00\x00').decode())
        fields, tail = decode(event, spec)
        self.assertEqual(fields['Win32StartAddr'], 0x123456789abc)
        self.assertEqual(fields['TebBase'], 0x100000001)
        self.assertEqual(tail, '0000')
        for key, value in [('flags', 0), ('version', 2), ('opcode', 36)]:
            bad = dict(event, **{key:value})
            with self.assertRaises(AssertionError): decode(bad, spec)
        with self.assertRaises(AssertionError):
            decode(dict(event, payload=base64.b64encode(b'\x00'*71).decode()), spec)

    def test_schema_mismatch_rejected(self):
        schema = copy.deepcopy(self.schema())
        prop = next(p for p in schema['properties'] if p['name'] == 'Win32StartAddr')
        prop['qualifiers'] = [q for q in prop['qualifiers'] if q['name'] != 'pointer']
        with self.assertRaises(AssertionError): layout(schema)

    def test_ambiguous_and_half_open_module_mapping(self):
        m = dict(base=100, size=20, recorded_path='library.dll', sha256='hash')
        self.assertEqual(module_at(100, [m])['rva'], 0)
        self.assertIsNone(module_at(120, [m])['module'])
        self.assertTrue(module_at(110, [m, dict(m, recorded_path='other.dll')])['ambiguous'])
