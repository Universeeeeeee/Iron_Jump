import unittest
from analyze import grouped

class Labels(unittest.TestCase):
    def test_duplicate_generated_names_preserve_all_counts(self):
        rows=[dict(function=dict(file='<string>',name='__init__',line=2),calls=n) for n in (3,7)];r=next(iter(grouped(rows).values()));self.assertEqual(r['calls'],10);self.assertTrue(r['ambiguous']);self.assertEqual(r['records'],2)
    def test_distinct_source_lines_remain_separate(self):
        rows=[dict(function=dict(file='module.py',name='f',line=n),calls=3) for n in (1,2)];self.assertEqual(len(grouped(rows)),2)

if __name__=='__main__':unittest.main()
