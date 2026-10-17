"""Offline external-window acceptance, keeping every target PID separate."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from align_clock import main as clock_mapping


def validate_observations(record):
    observations=record['external_observation']
    before,after=observations['before'],observations['after']
    if not before or len(before)!=len(after):
        raise ValueError('Incomplete before/after thread observations')
    identities=set()
    labels=set()
    for a,b in zip(before,after):
        identity=(a['pid'],a['tid'])
        label=(a['pid'],a.get('name',a['role']))
        if identity in identities or label in labels:
            raise ValueError('Duplicate thread identity or label')
        identities.add(identity);labels.add(label)
        keys=['pid','tid','role','creation_100ns']
        if any(a[k]!=b[k] for k in keys) or a.get('name')!=b.get('name'):
            raise ValueError('Thread identity changed across the window')
        if not a['active'] or not b['active']:
            raise ValueError('Target thread exited')
        if b['start']['qpc_before']<=a['end']['qpc_after']:
            raise ValueError('Empty or reversed observation window')
        if any(b[k]<a[k] for k in ['kernel_100ns','user_100ns','cycles']):
            raise ValueError('Thread counter regressed')
    return observations


def main(a):
    record=json.loads((a.window/'record.json').read_text())
    observations=validate_observations(record)
    mapping=clock_mapping(record)  # Mandatory bounded host clock, before any decoder.
    source=a.window/'trace.etl'
    source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'clock_mapping.json').write_text(json.dumps(mapping,indent=2)+'\n')
    acceptance=dict(source_etl_sha256=source_sha,measurement_acceptance_pass=False,
                    quantitative_field_attribution_ready=False,requires_actual_load_calibration=True)
    try:
        summary=a.output/'tracerpt_summary.txt'
        scan=subprocess.run(['tracerpt',str(source),'-o','NUL','-summary',str(summary),'-y'],capture_output=True,check=True)
        (a.output/'tracerpt_process.json').write_text(json.dumps(dict(returncode=scan.returncode,
            stdout=scan.stdout.decode(errors='replace'),stderr=scan.stderr.decode(errors='replace')),indent=2)+'\n')
        reports={}
        for pid in sorted({t['pid'] for t in observations['before']}):
            folder=a.output/str(pid)
            (folder/'fixture').mkdir(parents=True,exist_ok=False)
            threads={}
            for before,after in zip(observations['before'],observations['after']):
                if before['pid']!=pid: continue
                def convert(value):
                    return dict(value,clock=dict(value['end'],qpc_before=value['start']['qpc_before'],
                                                 qpc_after=value['end']['qpc_after']))
                threads[before.get('name',before['role'])]=dict(before=convert(before),after=convert(after),work=None)
            fixture=dict(pid=pid,threads=threads,start=record['start'],end=record['end'],
                         synthetic_only=record.get('synthetic_targets',False))
            (folder/'fixture/fixture.json').write_text(json.dumps(fixture,indent=2)+'\n')
            (folder/'record.json').write_text(json.dumps(dict(record,source_etl_sha256=source_sha),indent=2)+'\n')
            subprocess.run([str(a.reader),str(source),str(pid),
                            ','.join(str(t['before']['tid']) for t in threads.values()),str(folder/'decoded')],check=True)
            subprocess.run([a.python,str(Path(__file__).with_name('symbolize.py')),
                            str(folder/'decoded/events.jsonl'),str(folder/'symbols03.json')],check=True)
            from analyze import quality
            from report import independent_scan
            result=quality(folder)
            result['independent_scan']=independent_scan(folder,summary)
            result['measurement_acceptance_pass']=result['quality_pass'] and result['independent_scan']['passed']
            reports[str(pid)]=dict(quality_pass=result['quality_pass'],independent_scan_pass=result['independent_scan']['passed'],
                                   measurement_acceptance_pass=result['measurement_acceptance_pass'])
            (folder/'quality.json').write_text(json.dumps(result,indent=2)+'\n')
        acceptance['processes']=reports
        acceptance['source_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==source_sha
        acceptance['measurement_acceptance_pass']=acceptance['source_unchanged'] and all(r['measurement_acceptance_pass'] for r in reports.values())
    except Exception as error:
        acceptance['failure']=repr(error)
        raise
    finally:
        (a.output/'acceptance.json').write_text(json.dumps(acceptance,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('window',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--reader',type=Path,default=Path(__file__).with_name('ReadStacks.exe'))
    p.add_argument('--python',default='D:/conda/python.exe')
    main(p.parse_args())
