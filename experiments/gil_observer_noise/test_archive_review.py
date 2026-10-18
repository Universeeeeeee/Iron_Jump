import unittest
from archive_review01 import manifest_paths


class ManifestPathsChecks(unittest.TestCase):
    def test_windows_separator(self):self.assertEqual(manifest_paths({'a\\b':'h'}),{'a/b':'h'})
    def test_posix_separator(self):self.assertEqual(manifest_paths({'a/b':'h'}),{'a/b':'h'})
    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):manifest_paths({'a/../b':'h'})
    def test_drive_rejected(self):
        with self.assertRaises(ValueError):manifest_paths({'C:a':'h'})
    def test_absolute_rejected(self):
        with self.assertRaises(ValueError):manifest_paths({'/a':'h'})
    def test_separator_collision_rejected(self):
        with self.assertRaises(ValueError):manifest_paths({'a\\b':'h','a/b':'h'})
    def test_case_collision_rejected(self):
        with self.assertRaises(ValueError):manifest_paths({'a/b':'h','A/B':'h'})


if __name__=='__main__':unittest.main()
