"""Reject stale cases and false-success streams without starting field work."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import field
from field import protocol, validate_marker


class FieldChecks(unittest.TestCase):
    def fixture(self):
        case = dict(mode='walk', trace='off', run_id='new01')
        marker = dict(run_id='new01', pid=100, tids=dict(gui=101, consumer=102, reader=103), armed_ns=1, host_ns=2)
        trace = dict(pid=100, os_thread_id=102, owns_gil=True, frames=[dict(name='f', filename='f.py', line=1)])
        rows = [dict(kind='init', schema=1, pid=100, error=None, qpc_frequency=10**7, qpc_end=1),
                dict(kind='sample', ordinal=0, pid=100, qpc_begin=2, qpc_end=3, traces=[trace]),
                dict(kind='complete', pid=100, samples_written=1, qpc=4)]
        return case, marker, rows

    def test_valid_marker_and_stream(self):
        c, m, r = self.fixture(); validate_marker(c, m)
        self.assertTrue(protocol(r, 100, 1))

    def test_run_rejected(self):
        c, m, _ = self.fixture(); c['mode'] = 'run'
        with self.assertRaises(ValueError): validate_marker(c, m)

    def test_etw_on_rejected(self):
        c, m, _ = self.fixture(); c['trace'] = 'on'
        with self.assertRaises(ValueError): validate_marker(c, m)

    def test_mismatched_case_rejected(self):
        c, m, _ = self.fixture(); m['run_id'] = 'old'
        with self.assertRaises(ValueError): validate_marker(c, m)

    def test_duplicate_role_tid_rejected(self):
        c, m, _ = self.fixture(); m['tids']['consumer'] = 101
        with self.assertRaises(ValueError): validate_marker(c, m)

    def test_failed_init_rejected(self):
        _, _, r = self.fixture(); r[0]['error'] = 'read failed'
        self.assertFalse(protocol(r, 100, 1))

    def test_missing_sample_rejected(self):
        _, _, r = self.fixture(); r.pop(1)
        self.assertFalse(protocol(r, 100, 1))

    def test_sample_error_rejected(self):
        _, _, r = self.fixture(); r[1] = dict(kind='error', error='read failed')
        self.assertFalse(protocol(r, 100, 1))

    def test_wrong_pid_rejected(self):
        _, _, r = self.fixture(); r[1]['traces'][0]['pid'] = 200
        self.assertFalse(protocol(r, 100, 1))

    def test_two_owners_rejected(self):
        _, _, r = self.fixture(); r[1]['traces'].append(dict(copy.deepcopy(r[1]['traces'][0]), os_thread_id=103))
        self.assertFalse(protocol(r, 100, 1))

    def test_owner_without_python_frames_rejected(self):
        _, _, r = self.fixture(); r[1]['traces'][0]['frames'] = []
        self.assertFalse(protocol(r, 100, 1))

    def controller_case(self, fault=None):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); formal = root / 'formal'
        runs = formal / 'experiments/single_usb_human_etw/runs'; runs.mkdir(parents=True)
        source = root / 'sources/experiments/gil_timestamped'; source.mkdir(parents=True)
        (source / 'field_plan01.json').write_text('{}')
        series = root / 'series'; series.mkdir()
        tool = root / 'observer.exe'; tool.write_bytes(b'synthetic placeholder, never executed')
        args = SimpleNamespace(output=series / 'run01', tool=tool)
        c, m, rows = self.fixture()
        def new_case(_):
            case = runs / 'new01'; case.mkdir(exist_ok=True)
            (case / 'case.json').write_text(json.dumps(c))
            (case / 'formal_started.json').write_text(json.dumps(m))
        def prepare(*_, **__):
            (args.output / 'targets.json').write_text('[]')
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        child = Mock(pid=999, returncode=0); child.poll.return_value = 0
        if fault == 'timeout':
            child.wait.side_effect = field.subprocess.TimeoutExpired('observer', 15)
            child.poll.return_value = None
        def launch(*_, **__):
            (args.output / 'samples.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            return child
        counters = [dict(creation_100ns=10, active=True)]
        observer = Mock()
        observer.snapshot.side_effect = [counters, OSError('counter read failed') if fault == 'counter' else counters]
        plan = dict(formal_root=str(formal), wait_seconds=1, formal_offset_ns=0,
                    start_lateness_ns_max=10**10, count=1, period_ms=50, observer_sha256=field.sha(tool))
        with patch.object(field, 'HERE', source), patch.object(field, 'preflight'), \
             patch.object(field.time, 'sleep', side_effect=new_case), \
             patch.object(field.time, 'perf_counter_ns', return_value=10**9), \
             patch.object(field, 'Observer', return_value=observer), patch.object(field, 'anchor', return_value={}), \
             patch.object(field.subprocess, 'run', side_effect=prepare), \
             patch.object(field.subprocess, 'Popen', side_effect=launch), \
             patch.object(field.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
             contextlib.redirect_stdout(io.StringIO()):
            code = field.capture(args, plan)
        return code, json.loads((args.output / 'capture_record.json').read_text()), series / 'active.lock', child, observer

    def test_timeout_keeps_live_observer_and_fault_lock(self):
        code, record, lock, child, observer = self.controller_case('timeout')
        self.assertEqual(code, 1); self.assertTrue(lock.exists())
        self.assertTrue(record['observer_still_running']); self.assertTrue(record['errors'])
        child.kill.assert_not_called(); child.terminate.assert_not_called()
        observer.close.assert_called_once()

    def test_counter_failure_cannot_report_clean_completion(self):
        code, record, lock, _, _ = self.controller_case('counter')
        self.assertEqual(code, 1); self.assertTrue(lock.exists())
        self.assertNotIn('capture_stream_and_counters_complete', record)

    def test_success_releases_only_own_lock_without_qualifying_field(self):
        code, record, lock, child, _ = self.controller_case()
        self.assertEqual(code, 0); self.assertFalse(lock.exists())
        self.assertTrue(record['capture_stream_and_counters_complete'])
        self.assertFalse(record['field_attribution_ready']); self.assertFalse(record['actual_load_disturbance_pass'])
        child.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
