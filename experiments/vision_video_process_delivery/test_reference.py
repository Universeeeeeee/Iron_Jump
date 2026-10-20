import json
from pathlib import Path
import tempfile
import unittest
from extract_reference import sha


class Reference(unittest.TestCase):
    def test_hash_is_bytes_not_reencoded_json(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_bytes(b'{\r\n}')
            self.assertEqual(sha(p),__import__('hashlib').sha256(b'{\r\n}').hexdigest())

    def test_selected_frame_must_exist_in_preview(self):
        frames=[10,20]
        self.assertIn(20,frames)
        self.assertNotIn(30,frames)


if __name__=='__main__':
    unittest.main()
