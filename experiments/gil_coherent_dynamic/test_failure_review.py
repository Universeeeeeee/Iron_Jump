import copy
from pathlib import Path
import unittest
import review_failure
from verify import read

HERE=Path(__file__).resolve().parent
RAW=HERE.parent/'native_stack_capture/runs/gil_coherent_dynamic01/evidence01'


@unittest.skipUnless(RAW.exists(),'preserved private synthetic archive unavailable')
class RealFailureChecks(unittest.TestCase):
    def fixture(self):
        import json
        return [json.loads(l) for l in (RAW/'run01/samples.jsonl').read_text().splitlines()],read(RAW/'resolved01.json'),read(HERE/'result01.json')

    def test_original_failure_remains_failed(self):
        v=review_failure.inspect(*self.fixture());self.assertFalse(v['frozen_dynamic_control_pass']);self.assertEqual(v['failed_waiter_count'],5);self.assertTrue(v['all_failed_samples_explained_as_sleep_without_GIL_acquisition']);self.assertFalse(v['field_attribution_ready'])

    def test_unmatched_sleep_symbol_cannot_explain_failure(self):
        r,m,v=self.fixture();m=copy.deepcopy(m)
        for module in m['modules']:
            for a in module['resolved']:
                if a['symbol']=='pysleep':a['pdb_matched']=False
        self.assertFalse(review_failure.inspect(r,m,v)['all_failed_samples_explained_as_sleep_without_GIL_acquisition'])

    def test_wrong_owner_cannot_be_excused_as_sleep(self):
        r,m,v=self.fixture();v=copy.deepcopy(v)
        next(j for j in v['joins'] if not j['matches'])['owner_and_python_frame']=False
        self.assertFalse(review_failure.inspect(r,m,v)['all_failed_samples_explained_as_sleep_without_GIL_acquisition'])


if __name__=='__main__':unittest.main()
