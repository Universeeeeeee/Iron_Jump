import unittest
from spacing import busy
from classify import state,spacing_quality


class Rules(unittest.TestCase):
    def test_idle_is_included_in_windows_kernel_counter(self):
        a=dict(idle_100ns=0,kernel_including_idle_100ns=0,user_100ns=0)
        b=dict(idle_100ns=75,kernel_including_idle_100ns=90,user_100ns=10)
        self.assertEqual(busy(a,b),25)
        with self.assertRaises(AssertionError):busy(a,dict(b,idle_100ns=101))
    def test_cpu_not_frequency_or_gil_and_both_state_components_required(self):
        result=dict(preparation=dict(begin_ns=0,end_ns=5_000_000_000,thread_cpu_ns=4_900_000_000),
            consumer=dict(begin_ns=0,end_ns=4_000_000_000,thread_cpu_ns=3_900_000_000),
            model=dict(calls=[dict(begin_ns=0,end_ns=20_000_000)]))
        rules=dict(slow_prepare_ms_min=4300,slow_model_ms_min=30,fast_prepare_ms_max=3500,fast_model_ms_max=26)
        self.assertEqual(state(result,rules)['label'],'intermediate')
    def test_late_launch_does_not_become_short_gap(self):
        row=dict(previous_exit_observed_ns=0,requested_gap_seconds=5,child_launch_before_ns=8_000_000_000,system_samples=[])
        rules=dict(long_gap_seconds=300,maximum_launch_lateness_seconds=2)
        self.assertFalse(spacing_quality(row,rules)['spacing_pass'])
