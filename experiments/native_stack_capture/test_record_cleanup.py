"""Controller fault injection only: no native API, WPR or workload is launched."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import record


class RecordCleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.here = Path(temporary.name)
        for mode in ('cpu', 'wait'):
            (self.here / (mode + '.wprp')).write_text('mock profile')
        self.args = argparse.Namespace(mode='cpu', output=self.here / 'window',
                                       seconds=0.01, targets=None)
        self.lock = self.here / '.capture.lock'
        self.interval = 10000
        self.interval_calls = []
        self.set_error = self.restore_error = self.restore_readback = None
        self.command_errors = {}
        self.commands = []
        for name, value in [('HERE', self.here), ('anchor', lambda: {'mock': True}),
                            ('profile_interval', self.profile_interval)]:
            patcher = patch.object(record, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(record.subprocess, 'run', side_effect=self.run_command)
        patcher.start()
        self.addCleanup(patcher.stop)

    def profile_interval(self, value=None):
        self.interval_calls.append(value)
        if value is not None:
            self.interval = value  # Set succeeds before the injected query failure.
            if value == 100000 and self.set_error:
                raise self.set_error
            if value == 10000:
                if self.restore_error:
                    raise self.restore_error
                if self.restore_readback is not None:
                    self.interval = self.restore_readback
        return self.interval

    def run_command(self, args, **kwargs):
        self.commands.append(args)
        operation = args[1] if args[0] in ('wpr', 'logman') else 'fixture'
        failure = self.command_errors.get(operation)
        if isinstance(failure, BaseException):
            raise failure
        return subprocess.CompletedProcess(args, failure or 0, b'', b'')

    def log(self):
        return json.loads((self.args.output / 'record.json').read_text())

    def assert_cleanup(self, complete):
        self.assertEqual(self.log()['cleanup_complete'], complete)
        self.assertEqual(self.lock.exists(), not complete)

    def test_set_success_query_failure_still_restores(self):
        self.set_error = OSError('set readback failed')
        with self.assertRaisesRegex(OSError, 'set readback failed'):
            record.main(self.args)
        self.assertEqual(self.interval_calls, [None, 100000, 10000])
        self.assertEqual(self.interval, 10000)
        self.assertFalse(any(command[0] == record.sys.executable for command in self.commands))
        self.assertTrue(self.log()['interval_restore_ok'])
        self.assert_cleanup(True)

    def test_restore_query_failure_keeps_log_and_lock(self):
        self.restore_error = OSError('restore readback failed')
        with self.assertRaises(Exception):
            record.main(self.args)
        self.assertEqual(self.interval, 10000)  # A successful set alone is insufficient.
        self.assertIn('restore readback failed', self.log()['interval_restore_error'])
        self.assertFalse(self.log()['interval_restore_ok'])
        self.assert_cleanup(False)

    def test_set_and_restore_readback_failures_keep_original_failure_and_lock(self):
        self.set_error = OSError('set readback failed')
        self.restore_error = OSError('restore readback failed')
        with self.assertRaisesRegex(OSError, 'set readback failed'):
            record.main(self.args)
        self.assertEqual(self.interval_calls, [None, 100000, 10000])
        self.assertIn('set readback failed', self.log()['failure'])
        self.assertIn('restore readback failed', self.log()['interval_restore_error'])
        self.assert_cleanup(False)

    def test_restore_mismatch_keeps_log_and_lock(self):
        self.restore_readback = 20000
        with self.assertRaises(RuntimeError):
            record.main(self.args)
        self.assertEqual(self.log()['interval_restored_100ns'], 20000)
        self.assertFalse(self.log()['interval_restore_ok'])
        self.assert_cleanup(False)

    def test_stop_nonzero_still_restores_and_keeps_lock(self):
        self.command_errors['-stop'] = 1
        with self.assertRaises(RuntimeError):
            record.main(self.args)
        self.assertEqual(self.interval, 10000)
        self.assertFalse(self.log()['stop_ok'])
        self.assertIn('stop', self.log()['stop_error'].lower())
        self.assert_cleanup(False)
        commands_before = list(self.commands)
        log_before = self.log()
        with self.assertRaises(FileExistsError):
            record.main(self.args)
        self.assertEqual(self.commands, commands_before)
        self.assertEqual(self.log(), log_before)

    def test_stop_exception_still_restores_and_keeps_log_and_lock(self):
        self.command_errors['-stop'] = OSError('stop transport failed')
        with self.assertRaises(Exception):
            record.main(self.args)
        self.assertEqual(self.interval, 10000)
        self.assertIn('stop transport failed', self.log()['stop_error'])
        self.assertFalse(self.log()['stop_ok'])
        self.assert_cleanup(False)

    def test_capture_and_both_cleanup_failures_are_retained(self):
        self.command_errors['fixture'] = ValueError('capture failed')
        self.command_errors['-stop'] = OSError('stop failed')
        self.restore_error = OSError('restore failed')
        with self.assertRaisesRegex(ValueError, 'capture failed'):
            record.main(self.args)
        log = self.log()
        self.assertIn('capture failed', log['failure'])
        self.assertIn('stop failed', log['stop_error'])
        self.assertIn('restore failed', log['interval_restore_error'])
        self.assert_cleanup(False)

    def test_capture_failure_with_confirmed_cleanup_releases_lock(self):
        self.command_errors['fixture'] = ValueError('capture failed')
        with self.assertRaisesRegex(ValueError, 'capture failed'):
            record.main(self.args)
        self.assertIn('capture failed', self.log()['failure'])
        self.assert_cleanup(True)

    def test_interrupt_during_set_still_restores(self):
        self.set_error = KeyboardInterrupt('interrupted readback')
        with self.assertRaises(KeyboardInterrupt):
            record.main(self.args)
        self.assertEqual(self.interval, 10000)
        self.assertIn('interrupted readback', self.log()['failure'])
        self.assert_cleanup(True)

    def test_success_releases_lock_and_only_stops_owned_instance(self):
        record.main(self.args)
        log = self.log()
        self.assertTrue(log['stop_ok'])
        self.assertTrue(log['interval_restore_ok'])
        for command in self.commands:
            if command[0] == 'wpr':
                self.assertEqual(command[-2:], ['-instancename', log['instance']])
        self.assert_cleanup(True)

    def test_wait_cleanup_failure_keeps_lock_without_interval_change(self):
        self.args.mode = 'wait'
        self.command_errors['-stop'] = 1
        with self.assertRaises(RuntimeError):
            record.main(self.args)
        self.assertEqual(self.interval_calls, [])
        self.assert_cleanup(False)

    def test_existing_lock_is_preserved_without_actions(self):
        self.lock.write_text('old failed window')
        with self.assertRaises(FileExistsError):
            record.main(self.args)
        self.assertEqual(self.lock.read_text(), 'old failed window')
        self.assertEqual(self.commands, [])
        self.assertFalse(self.args.output.exists())

    def test_log_write_failure_keeps_lock(self):
        with patch.object(Path, 'write_text', side_effect=OSError('disk failed')):
            with self.assertRaisesRegex(OSError, 'disk failed'):
                record.main(self.args)
        self.assertTrue(self.lock.exists())
        self.assertEqual(self.interval, 10000)

    def test_end_anchor_failure_cannot_hide_cleanup_fault_log(self):
        self.command_errors['-stop'] = 1
        with patch.object(record, 'anchor', side_effect=[{'mock': True}, OSError('clock failed')]):
            with self.assertRaises(RuntimeError):
                record.main(self.args)
        self.assertIn('clock failed', self.log()['end_error'])
        self.assertIn('stop', self.log()['stop_error'].lower())
        self.assert_cleanup(False)


if __name__ == '__main__':
    unittest.main()
