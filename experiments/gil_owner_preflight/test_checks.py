"""Reject misleading owner observations; no Windows process is started here."""
import json
from pathlib import Path
import tempfile
import unittest

from check import inspect, read


class OwnerChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.plan = read(Path(__file__).with_name('plan01.json'))

    def fixture(self, mode='held', thread=22, samples=None, errors=0):
        if samples is None:
            samples = 40 if mode == 'held' else 0
        folder = self.output / mode
        folder.mkdir()
        profile = {'shared': {'frames': [{'name': mode + '_sleep'}]},
                   'profiles': [{'name': f'Thread {thread}', 'samples': [[0]] * samples}] if samples else []}
        (folder / 'profile.json').write_text(json.dumps(profile))
        (self.output / (mode + '_sampler.log')).write_text(f'Samples: {samples} Errors: {errors}')
        return dict(mode=mode, ready={'tids': {'sleeper': 22}}, begin={'host_ns': 0},
            end={'host_ns': 2000000000}, sampler_bracket_ns=[400000000, 800000000],
            sampler_returncode=0, target_returncode=0,
            heartbeat_observations=[[i, 10 if mode == 'held' else i * 2] for i in range(21)],
            OS_thread_state_before={'state': 'Wait', 'reason': 'ExecutionDelay'},
            OS_thread_state_after={'state': 'Wait', 'reason': 'ExecutionDelay'})

    def rejected(self, record, check):
        result = inspect(record, self.output, self.plan)
        self.assertFalse(result['correctness_pass'])
        self.assertFalse(result['checks'][check])

    def test_valid_known_holder(self):
        self.assertTrue(inspect(self.fixture(), self.output, self.plan)['correctness_pass'])

    def test_valid_released_control(self):
        self.assertTrue(inspect(self.fixture('released'), self.output, self.plan)['correctness_pass'])

    def test_wrong_native_thread_rejected(self):
        self.rejected(self.fixture(thread=23), 'no_known_wrong_TID')

    def test_heartbeat_breaks_reported_hold(self):
        record = self.fixture()
        record['heartbeat_observations'][-1][1] += 1
        self.rejected(record, 'heartbeat_delivery')

    def test_released_sleep_must_not_be_owner(self):
        self.rejected(self.fixture('released', samples=1), 'expected_GIL_filter')

    def test_read_errors_rejected(self):
        self.rejected(self.fixture(errors=1), 'sampler_reported_no_errors')

    def test_os_does_not_confirm_sleep(self):
        record = self.fixture()
        record['OS_thread_state_before'] = {'state': 'Running', 'reason': ''}
        self.rejected(record, 'OS_sleep_before_after')

    def test_sample_window_crosses_boundary(self):
        record = self.fixture()
        record['sampler_bracket_ns'][0] = 100000000
        self.rejected(record, 'sampler_inside_sleep_bracket')

    def test_other_reported_owner_during_known_hold(self):
        record = self.fixture()
        path = self.output / 'held/profile.json'
        profile = read(path)
        profile['shared']['frames'].append({'name': 'unrelated'})
        profile['profiles'].append({'name': 'Thread 99', 'samples': [[1]]})
        path.write_text(json.dumps(profile))
        self.rejected(record, 'held_has_no_other_GIL_thread')


if __name__ == '__main__':
    unittest.main()
