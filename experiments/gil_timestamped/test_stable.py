"""Reject misleading time/identity joins without starting any process."""
import copy
import unittest

from check_stable import inspect


class TimestampChecks(unittest.TestCase):
    def fixture(self):
        record = dict(mode='held', ready={'pid': 10, 'tids': {'sleeper': 22}},
            begin={'host_ns': 0}, end={'host_ns': 2000000000},
            anchors=[dict(before_ns=0, after_ns=2, qpc=1, frequency=10**9),
                     dict(before_ns=1000000, after_ns=1000002, qpc=1000001, frequency=10**9)],
            heartbeat_observations=[[0, 5], [1, 5]],
            OS_before={'state': 'Wait', 'reason': 'ExecutionDelay'},
            OS_after={'state': 'Wait', 'reason': 'ExecutionDelay'},
            complete={'completed': True, 'pid': 10}, target_returncode=0,
            sampler_returncode=0, errors=[], forced_cleanup=[], stderr='',
            external_bracket_ns=[200000000, 500000000])
        trace = dict(pid=10, os_thread_id=22, owns_gil=True,
                     frames=[dict(name='held_sleep', filename='fixture.py', line=1)])
        rows = [dict(kind='init', schema=1, error=None, pid=10, qpc_frequency=10**9,
                     qpc_begin=200000000, qpc_end=250000000)]
        rows += [dict(kind='sample', ordinal=i, pid=10,
                      qpc_begin=300000000 + i * 50000000,
                      qpc_end=301000000 + i * 50000000, traces=[copy.deepcopy(trace)]) for i in range(2)]
        rows.append(dict(kind='complete', pid=10, samples_written=2, qpc=450000000))
        plan = dict(count=2, clock_uncertainty_ns_max=1000000,
                    phase_margin_ns=200000000, released_heartbeat_increment_floor=20)
        return record, rows, plan

    def reject(self, record, rows, plan, check):
        result = inspect(record, rows, plan)
        self.assertFalse(result['stable_timestamped_correctness_pass'])
        self.assertFalse(result['checks'][check])

    def test_keeps_whole_bracket_and_clock_uncertainty(self):
        result = inspect(*self.fixture())
        self.assertTrue(result['stable_timestamped_correctness_pass'])
        self.assertEqual(result['converted_brackets_ns'][0], [299999999, 301000001])
        self.assertFalse(result['field_attribution_ready'])

    def test_missing_sample_rejected(self):
        r, rows, p = self.fixture(); rows.pop(1)
        self.reject(r, rows, p, 'complete')

    def test_error_row_not_filtered_into_success(self):
        r, rows, p = self.fixture(); rows.insert(2, dict(kind='error', error='read failed'))
        self.reject(r, rows, p, 'no_extra_or_error_rows')

    def test_ordinal_gap_rejected(self):
        r, rows, p = self.fixture(); rows[2]['ordinal'] = 2
        self.reject(r, rows, p, 'ordered_brackets')

    def test_regressing_time_rejected(self):
        r, rows, p = self.fixture(); rows[2]['qpc_begin'] = 299000000
        self.reject(r, rows, p, 'ordered_brackets')

    def test_wrong_holder_rejected(self):
        r, rows, p = self.fixture(); rows[1]['traces'][0]['os_thread_id'] = 23
        self.reject(r, rows, p, 'all_owner_checks')

    def test_failed_resume_cannot_pass(self):
        r, rows, p = self.fixture(); r['complete']['completed'] = False
        self.reject(r, rows, p, 'all_owner_checks')

    def test_read_crossing_control_phase_rejected(self):
        r, rows, p = self.fixture(); rows[1]['qpc_begin'] = 190000000
        self.reject(r, rows, p, 'all_owner_checks')

    def test_external_bracket_not_shrunk(self):
        r, rows, p = self.fixture(); r['external_bracket_ns'][1] = 349000000
        self.reject(r, rows, p, 'samples_inside_external_bracket')

    def test_wide_clock_does_not_pass_on_midpoint(self):
        r, rows, p = self.fixture()
        for a in r['anchors']:
            a['before_ns'] -= 2000000; a['after_ns'] += 2000000
        self.reject(r, rows, p, 'clock_mapping')

    def test_frequency_disagreement_rejected(self):
        r, rows, p = self.fixture(); r['anchors'][1]['frequency'] *= 2
        with self.assertRaises(AssertionError):
            inspect(r, rows, p)


if __name__ == '__main__':
    unittest.main()
