"""Fault injection for single-snapshot interpretation; no target is launched."""
import copy
import unittest

from dump_check import inspect


class DumpChecks(unittest.TestCase):
    def fixture(self, mode='held'):
        record = dict(mode=mode, ready={'pid': 10, 'tids': {'sleeper': 22}},
            begin={'host_ns': 0}, end={'host_ns': 2000000000},
            sampler_bracket_ns=[300000000, 400000000],
            heartbeat_observations=[[200000000, 5], [900000000, 5 if mode == 'held' else 45]],
            OS_before={'state': 'Wait', 'reason': 'ExecutionDelay'},
            OS_after={'state': 'Wait', 'reason': 'ExecutionDelay'},
            complete={'completed': True, 'pid': 10},
            target_returncode=0, sampler_returncode=0, errors=[], forced_cleanup=[])
        traces = [dict(pid=10, os_thread_id=22, owns_gil=mode == 'held',
                       frames=[dict(name=mode + '_sleep', filename='fixture.py', line=1)])]
        return record, traces

    def result(self, record, traces, stderr=''):
        return inspect(record, traces, stderr,
                       dict(phase_margin_ns=200000000, released_heartbeat_increment_floor=20))

    def reject(self, record, traces, check, stderr=''):
        result = self.result(record, traces, stderr)
        self.assertFalse(result['stable_correctness_pass'])
        self.assertFalse(result['checks'][check])

    def test_known_holder(self):
        self.assertTrue(self.result(*self.fixture())['stable_correctness_pass'])

    def test_released_zero_owner_is_valid_not_owner_identity(self):
        result = self.result(*self.fixture('released'))
        self.assertTrue(result['stable_correctness_pass'])
        self.assertEqual(result['owner_native_TIDs'], [])
        self.assertFalse(result['field_attribution_ready'])

    def test_wrong_pid(self):
        r, t = self.fixture(); t[0]['pid'] += 1
        self.reject(r, t, 'schema_and_PID')

    def test_missing_native_tid(self):
        r, t = self.fixture(); t[0]['os_thread_id'] = None
        self.reject(r, t, 'schema_and_PID')

    def test_wrong_holder(self):
        r, t = self.fixture(); t[0]['os_thread_id'] += 1
        self.reject(r, t, 'known_owner')

    def test_duplicate_tid(self):
        r, t = self.fixture(); t.append(copy.deepcopy(t[0]))
        self.reject(r, t, 'unique_native_TIDs')

    def test_two_owners(self):
        r, t = self.fixture(); t.append(dict(t[0], os_thread_id=23))
        self.reject(r, t, 'at_most_one_owner')

    def test_released_sleeper_cannot_own(self):
        r, t = self.fixture('released'); t[0]['owns_gil'] = True
        self.reject(r, t, 'known_owner')

    def test_missing_python_frame(self):
        r, t = self.fixture(); t[0]['frames'] = []
        self.reject(r, t, 'known_sleep_frame')

    def test_held_heartbeat_contradiction(self):
        r, t = self.fixture(); r['heartbeat_observations'][-1][1] += 1
        self.reject(r, t, 'heartbeat_delivery')

    def test_released_heartbeat_stalled(self):
        r, t = self.fixture('released'); r['heartbeat_observations'][-1][1] = 5
        self.reject(r, t, 'heartbeat_delivery')

    def test_snapshot_crosses_phase(self):
        r, t = self.fixture(); r['sampler_bracket_ns'][1] = 1900000000
        self.reject(r, t, 'bracket_inside_phase')

    def test_no_post_dump_target_execution(self):
        r, t = self.fixture(); r['complete']['completed'] = False
        self.reject(r, t, 'target_executed_after_dump')

    def test_os_does_not_confirm_sleep(self):
        r, t = self.fixture(); r['OS_after']['state'] = 'Ready'
        self.reject(r, t, 'sleep_OS_before_after')

    def test_forced_cleanup_cannot_pass(self):
        r, t = self.fixture(); r['forced_cleanup'] = ['target']
        self.reject(r, t, 'no_error_or_forced_cleanup')

    def test_success_exit_does_not_hide_stderr(self):
        r, t = self.fixture()
        self.reject(r, t, 'no_stderr', 'Failed to read thread')


if __name__ == '__main__':
    unittest.main()
