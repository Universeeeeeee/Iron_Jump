"""Reject incomplete external observations before invoking any decoder."""
import argparse
import json
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import split_field


def anchor(q):
    return dict(qpc_before=q,qpc_after=q+1,frequency=10000000,filetime_100ns=5000+q,
                perf_before_ns=q*100-10,perf_after_ns=(q+1)*100+10)


def record():
    row=dict(pid=100,tid=101,role='gui',creation_100ns=1,kernel_100ns=0,user_100ns=0,
             cycles=1,active=True,start=anchor(20),end=anchor(30))
    after=dict(row,start=anchor(100),end=anchor(110),cycles=2)
    return dict(mode='wait',start=anchor(1),end=anchor(200),commands=[],
                external_observation=dict(before=[row],after=[after]))


class SplitTests(unittest.TestCase):
    def invoke(self, value):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);window=root/'window';window.mkdir()
            (window/'record.json').write_text(json.dumps(value))
            (window/'trace.etl').write_bytes(b'synthetic test input, never decoded')
            args=argparse.Namespace(window=window,output=root/'split',reader=Path('unused.exe'),python='unused')
            with patch.object(split_field.subprocess,'run',return_value=SimpleNamespace(returncode=0)), patch('analyze.quality',return_value={'quality_pass':True}):
                split_field.main(args)

    def test_missing_after_row_rejected(self):
        value=record();value['external_observation']['after']=[]
        with self.assertRaises(ValueError):self.invoke(value)

    def test_changed_thread_identity_rejected(self):
        value=record();value['external_observation']['after'][0]['tid']=999
        with self.assertRaises(ValueError):self.invoke(value)

    def test_one_sided_host_clock_rejected(self):
        value=record()
        for row in [value['start'],value['end']]+[t[k] for g in ['before','after'] for t in value['external_observation'][g] for k in ['start','end']]:
            row.pop('perf_before_ns')
        with self.assertRaises(ValueError):self.invoke(value)

    def test_failed_scan_cannot_leave_a_success_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);window=root/'window';window.mkdir()
            (window/'record.json').write_text(json.dumps(record()))
            (window/'trace.etl').write_bytes(b'never decoded')
            args=argparse.Namespace(window=window,output=root/'split',reader=Path('unused.exe'),python='unused')
            with patch.object(split_field.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['tracerpt'])):
                with self.assertRaises(subprocess.CalledProcessError):split_field.main(args)
            self.assertFalse(json.loads((args.output/'acceptance.json').read_text())['measurement_acceptance_pass'])

    def test_independent_count_gate_never_licenses_field_attribution(self):
        for scanned,expected in [(9,False),(8,True)]:
            with self.subTest(scanned=scanned),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);window=root/'window';window.mkdir()
                (window/'record.json').write_text(json.dumps(record()))
                (window/'trace.etl').write_bytes(b'never decoded')
                args=argparse.Namespace(window=window,output=root/'split',reader=Path('unused.exe'),python='unused')
                def command(argv,**kwargs):
                    if argv[0]=='tracerpt':
                        Path(argv[argv.index('-summary')+1]).write_text('Total Events Lost 0\n| '+str(scanned)+' StackWalk 0 Stack 2 {def2fe46-7bd6-4b80-bd94-f57fe20d0ce3}|\n')
                    elif argv[0]=='unused.exe':
                        decoded=Path(argv[-1]);decoded.mkdir()
                        (decoded/'metadata.json').write_text(json.dumps(dict(shapes={'def2fe46-7bd6-4b80-bd94-f57fe20d0ce3/32/v2/len24':8})))
                    return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
                with patch.object(split_field.subprocess,'run',side_effect=command),patch('analyze.quality',return_value={'quality_pass':True}):
                    split_field.main(args)
                result=json.loads((args.output/'acceptance.json').read_text())
                self.assertEqual(result['measurement_acceptance_pass'],expected)
                self.assertFalse(result['quantitative_field_attribution_ready'])


if __name__=='__main__':unittest.main()
