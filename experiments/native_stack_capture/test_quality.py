"""Tests for evidence rejection and CPU/wait isolation; no Windows capture needed."""
import unittest
import xml.etree.ElementTree as ET
from analyze import HERE, stack_info, clock_residual_ms
from align_clock import mapping


class QualityTests(unittest.TestCase):
    def symbols(self, names):
        return {str(n):dict(symbol=name,module='test.dll',rva=n) for n,name in enumerate(names,1)}

    def test_restore_thread_without_gil_is_not_gil(self):
        s=self.symbols(['NtWaitForSingleObject','PyEval_RestoreThread','RtlUserThreadStart'])
        self.assertEqual(stack_info([(1,2,3)],s)['families'],[])

    def test_truncated_gil_chain_rejected(self):
        s=self.symbols(['NtWaitForSingleObject','take_gil','PyEval_RestoreThread'])
        r=stack_info([(1,2,3)],s)
        self.assertFalse(r['root_complete'])
        self.assertEqual(r['families'],[])

    def test_split_kernel_and_user_are_not_ambiguous(self):
        s=self.symbols(['NtWaitForSingleObject','take_gil','RtlUserThreadStart'])
        r=stack_info([(0xffff000000001000,),(1,2,3)],s)
        self.assertTrue(r['has_kernel'])
        self.assertFalse(r['ambiguous'])
        self.assertEqual(r['families'],['gil_wait_chain'])

    def test_multiple_user_stacks_not_complete(self):
        s=self.symbols(['NtWaitForSingleObject','take_gil','RtlUserThreadStart'])
        r=stack_info([(1,2,3),(2,3)],s)
        self.assertTrue(r['ambiguous'])
        self.assertFalse(r['root_complete'])

    def test_unknown_frame_remains_unknown(self):
        r=stack_info([(1,2,3)],self.symbols(['NtWaitForSingleObject']))
        self.assertEqual(r['unmapped_frames'],2)
        self.assertEqual(r['unknown_symbol_frames'],2)
        self.assertFalse(r['root_complete'])

    def test_qt_and_system_witnesses(self):
        s=self.symbols(['NtWaitForSingleObject','QWaitCondition::wait','RtlUserThreadStart'])
        self.assertEqual(stack_info([(1,2,3)],s)['families'],['qt_wait_chain'])
        s=self.symbols(['NtDelayExecution','SleepEx','RtlUserThreadStart'])
        self.assertEqual(stack_info([(1,2,3)],s)['families'],['system_timer_wait_chain'])

    def test_clock_uses_brackets_not_wide_midpoint(self):
        anchors=[dict(qpc_before=10,qpc_after=100010,filetime_100ns=5010)]
        samples=[dict(qpc=20,filetime_100ns=5020)]
        self.assertEqual(clock_residual_ms(anchors,samples,10000000),0)

    def test_clock_mismatch_rejected(self):
        anchors=[dict(qpc_before=10,qpc_after=20,filetime_100ns=5015)]
        samples=[dict(qpc=20,filetime_100ns=105020)]
        self.assertGreater(clock_residual_ms(anchors,samples,10000000),1)

    def test_missing_clock_evidence_rejected(self):
        with self.assertRaises(ValueError): clock_residual_ms([],[],10000000)

    def test_host_mapping_rejects_one_sided_anchor(self):
        with self.assertRaises(ValueError):
            mapping([dict(frequency=10000000,perf_ns=2000,qpc_before=10,qpc_after=11)])

    def test_host_mapping_retains_uncertainty(self):
        r=mapping([dict(frequency=10000000,perf_before_ns=990,perf_after_ns=1110,qpc_before=10,qpc_after=11)])
        self.assertLessEqual(r['host_ns_offset_lower'],0)
        self.assertGreaterEqual(r['host_ns_offset_upper'],0)
        self.assertEqual(r['uncertainty_ns'],220)

    def test_profiles_do_not_enable_each_other(self):
        for mode, expected in [('cpu','SampledProfile'),('wait','CSwitch')]:
            tree=ET.parse(HERE/(mode+'.wprp'))
            self.assertEqual([n.attrib['Value'] for n in tree.findall('.//Stack')],[expected])
            keywords={n.attrib['Value'] for n in tree.findall('.//Keyword')}
            self.assertEqual(keywords,{'ProcessThread','Loader',expected}|({'ReadyThread'} if mode=='wait' else set()))


if __name__=='__main__': unittest.main()
