import unittest
from run import restore

class Inputs(unittest.TestCase):
    def test_no_owner(self):self.assertEqual(restore(dict(input=None)),{})
    def test_all_decisions_retained(self):
        r=restore(dict(input=[1,[2],[[3,'pending',1],[4,'associated',1]]]))
        self.assertEqual(r['recovery']['source_ids'],[2]);self.assertEqual(len(r['source_decisions']),2)

if __name__=='__main__':unittest.main()
