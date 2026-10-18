"""Fault injection for oracle joins; no native target is started."""
import unittest

from check_changing import inspect
import test_stable


class ChangingChecks(unittest.TestCase):
    def fixture(self):
        r, rows, p = test_stable.TimestampChecks().fixture()
        p.update(eligible_floor=2, per_holder_floor=1)
        r['ready']['tids'] = {'1': 22, '2': 23}
        r['observer_returncode'] = 0
        r['complete']['host_ns'] = 2000000000
        r['oracle'] = [[299000000, 299000001, 2, 1, 22, 1, 2],
                       [302000000, 302000001, 2, 1, 22, 1, 2],
                       [349000000, 349000001, 4, 2, 23, 2, 4],
                       [352000000, 352000001, 4, 2, 23, 2, 4]]
        rows[1]['traces'][0]['frames'][0]['name'] = 'hold_a'
        rows[2]['traces'][0]['os_thread_id'] = 23
        rows[2]['traces'][0]['frames'][0]['name'] = 'hold_b'
        return r, rows, p

    def reject(self, r, rows, p, name):
        result = inspect(r, rows, p)
        self.assertFalse(result['controlled_changing_oracle_pass'])
        self.assertFalse(result['checks'][name])

    def test_two_bracketed_holders(self):
        result = inspect(*self.fixture())
        self.assertTrue(result['controlled_changing_oracle_pass'])
        self.assertEqual(result['eligible_counts'], {'1': 1, '2': 1})

    def test_epoch_change_is_unknown_not_a_successful_join(self):
        r, rows, p = self.fixture(); r['oracle'][1][2] = r['oracle'][1][6] = 4
        self.reject(r, rows, p, 'independent_coverage')

    def test_wrong_owner_rejected(self):
        r, rows, p = self.fixture(); rows[1]['traces'][0]['os_thread_id'] = 99
        self.reject(r, rows, p, 'every_eligible_sample_matches')

    def test_wrong_python_path_rejected(self):
        r, rows, p = self.fixture(); rows[1]['traces'][0]['frames'][0]['name'] = 'hold_b'
        self.reject(r, rows, p, 'every_eligible_sample_matches')

    def test_heartbeat_contradiction_rejected(self):
        r, rows, p = self.fixture(); r['oracle'][1][5] += 1
        self.reject(r, rows, p, 'held_oracle_heartbeat_still')

    def test_marker_changed_without_epoch_rejected(self):
        r, rows, p = self.fixture(); r['oracle'][1][4] = 99
        self.reject(r, rows, p, 'same_epoch_consistent')

    def test_no_completion_rejected(self):
        r, rows, p = self.fixture(); rows.pop()
        self.reject(r, rows, p, 'complete')

    def test_error_record_rejected(self):
        r, rows, p = self.fixture(); rows.insert(2, dict(kind='error'))
        self.reject(r, rows, p, 'no_error_rows')

    def test_both_owners_required(self):
        r, rows, p = self.fixture(); r['oracle'] = r['oracle'][:2]
        self.reject(r, rows, p, 'independent_coverage')

    def test_window_outside_external_bracket_rejected(self):
        r, rows, p = self.fixture(); r['external_bracket_ns'][1] = 340000000
        self.reject(r, rows, p, 'all_read_windows_bounded')


if __name__ == '__main__':
    unittest.main()
