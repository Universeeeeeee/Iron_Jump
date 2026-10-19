import unittest
from check import check


class Contract(unittest.TestCase):
    def data(self):
        return dict(handler_restored=True,same_exact_QLabel_native_export=True,source_and_modules_match_plan=True,
            gui_tid=7,call_qpc={'1':[10,20],'2':[30,40]},
            rows=[dict(tid=7,phase=1,message_type=1,gil=1,qpc=15),dict(tid=7,phase=2,message_type=1,gil=0,qpc=35)])

    def test_dummy_always_held_or_always_free_oracle_fails(self):
        for gil in (0,1):
            d=self.data()
            for row in d['rows']: row['gil']=gil
            with self.assertRaises(AssertionError): check(d)

    def test_wrong_thread_time_or_restore_fails(self):
        for key,value in [('tid',8),('qpc',25),('message_type',2)]:
            d=self.data();d['rows'][0][key]=value
            with self.assertRaises(AssertionError): check(d)
        d=self.data();d['handler_restored']=False
        with self.assertRaises(AssertionError): check(d)

    def test_valid_contract_does_not_claim_field_root(self):
        self.assertFalse(check(self.data())['field_owner_or_root_proven'])
