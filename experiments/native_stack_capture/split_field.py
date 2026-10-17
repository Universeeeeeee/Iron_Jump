"""Offline per-PID export of a future external window. Never launches the application."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main(a):
    record = json.loads((a.window/'record.json').read_text())
    observations = record['external_observation']
    pids = sorted({t['pid'] for t in observations['before']})
    source_sha = hashlib.sha256((a.window/'trace.etl').read_bytes()).hexdigest()
    for pid in pids:
        folder = a.output/str(pid)
        (folder/'fixture').mkdir(parents=True,exist_ok=False)
        threads = {}
        for before,after in zip(observations['before'],observations['after']):
            if before['pid']!=pid: continue
            def convert(value):
                return dict(value, clock=dict(value['end'],qpc_before=value['start']['qpc_before'],
                                               qpc_after=value['end']['qpc_after']))
            threads[before.get('name',before['role'])] = dict(before=convert(before),after=convert(after),work=None)
        fixture = dict(pid=pid,threads=threads,start=record['start'],end=record['end'],synthetic_only=False)
        (folder/'fixture/fixture.json').write_text(json.dumps(fixture,indent=2)+'\n')
        (folder/'record.json').write_text(json.dumps(dict(record,source_etl_sha256=source_sha),indent=2)+'\n')
        subprocess.run([str(a.reader),str(a.window/'trace.etl'),str(pid),
                        ','.join(str(t['before']['tid']) for t in threads.values()),str(folder/'decoded')],check=True)
        subprocess.run([a.python,str(Path(__file__).with_name('symbolize.py')),
                        str(folder/'decoded/events.jsonl'),str(folder/'symbols03.json')],check=True)
        # Quality reports remain per process. Do not merge SDK counts into GUI GIL statistics.
        from analyze import quality
        (folder/'quality.json').write_text(json.dumps(quality(folder),indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('window',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--reader',type=Path,default=Path(__file__).with_name('ReadStacks.exe'))
    p.add_argument('--python',default='D:/conda/python.exe')
    main(p.parse_args())
