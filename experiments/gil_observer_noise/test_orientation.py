import unittest
from analyze import ordered_pairs
from noise_stats import contrast


def metric(v):return dict(wall_ns=v,thread_cpu_ns=v,cycles=v,blocks=[dict(raw_first=1,wall_ns=v)])


class PairOrientationChecks(unittest.TestCase):
    def test_ab_ba_preserve_on_over_off_not_cancel(self):
        specs=[];cases={}
        for i in range(1,9):
            for mode in (('off','on') if i%2 else ('on','off')):
                key=f'{i}_{mode}';specs.append(dict(id=key,pair=i,mode=mode,side=mode));cases[key]=metric(100 if mode=='off' else 102)
        v=contrast(ordered_pairs(specs,cases));self.assertAlmostEqual(v['metrics']['wall_ns']['geometric_relative_change'],.02)
    def test_aa_preserves_b_over_a(self):
        specs=[dict(id='b',pair=1,mode='on',side='b'),dict(id='a',pair=1,mode='on',side='a')];a,b=ordered_pairs(specs,{'a':1,'b':2})[0];self.assertEqual((a,b),(1,2))
    def test_one_case_rejected(self):
        with self.assertRaises(ValueError):ordered_pairs([dict(id='a',pair=1,mode='off',side='a')],{'a':1})
    def test_duplicate_aa_sides_rejected(self):
        specs=[dict(id=k,pair=1,mode='off',side='a') for k in ('a','b')]
        with self.assertRaises(ValueError):ordered_pairs(specs,{'a':1,'b':2})


if __name__=='__main__':unittest.main()
