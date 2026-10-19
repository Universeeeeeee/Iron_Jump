from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from observer import Observer
from engine import ground_source_review as source

class Inputs(unittest.TestCase):
    def test_original_called_and_mutations_separate(self):
        observer=Observer();original=source.assigned_sources;observer.enable()
        try:
            group={'recovery':{'owner_id':1,'source_ids':[2]},'source_decisions':[]}
            a=source.assigned_sources(group);b=source.assigned_sources(group);self.assertEqual(a,{2});self.assertIsNot(a,b)
            group['source_decisions'].append(dict(source_id=3,outcome='associated',owner_id=1));self.assertEqual(source.assigned_sources(group),{2,3});self.assertEqual(observer.result()['distinct_effective_inputs'],2)
        finally:observer.disable()
        self.assertIs(source.assigned_sources,original)
    def test_absent_owner(self):
        o=Observer();o.enable()
        try:self.assertEqual(source.assigned_sources({}),set());self.assertEqual(o.result()['calls'],1)
        finally:o.disable()

if __name__=='__main__':unittest.main()
