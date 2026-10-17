"""Re-evaluate preserved external ETL exports after an offline analyzer correction."""
import argparse
import hashlib
import json
from pathlib import Path
from analyze import quality
from report import independent_scan
from split_field import validate_observations
from align_clock import main as clock_mapping

HERE=Path(__file__).resolve().parent


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main(a):
    for case in sorted(a.runs.iterdir()):
        if not (case/'plan_reference.json').exists() or read(case/'window/record.json')['mode']=='off':continue
        record=read(case/'window/record.json')
        validate_observations(record)
        mapping=clock_mapping(record)
        old=read(case/'split/acceptance.json')
        source=case/'window/trace.etl'
        if sha(source)!=old['source_etl_sha256']:raise ValueError('Original ETL changed')
        output=case/a.subdir
        output.mkdir(exist_ok=False)
        reports={}
        for pid in sorted({str(t['pid']) for t in record['external_observation']['before']}):
            previous=case/'split'/pid
            result=quality(previous)
            result['independent_scan']=independent_scan(previous,case/'split/tracerpt_summary.txt')
            result['measurement_acceptance_pass']=result['quality_pass'] and result['independent_scan']['passed']
            result['recheck_provenance']=dict(previous_quality_sha256=sha(previous/'quality.json'),
                decoded_events_sha256=sha(previous/'decoded/events.jsonl'),symbols_sha256=sha(previous/'symbols03.json'),
                analyzer_sha256=sha(HERE/'analyze.py'))
            (output/pid).mkdir()
            (output/pid/'quality.json').write_text(json.dumps(result,indent=2)+'\n')
            reports[pid]=dict(quality_pass=result['quality_pass'],independent_scan_pass=result['independent_scan']['passed'],
                             measurement_acceptance_pass=result['measurement_acceptance_pass'])
        unchanged=sha(source)==old['source_etl_sha256']
        acceptance=dict(source_etl_sha256=old['source_etl_sha256'],source_unchanged=unchanged,
            processes=reports,clock_mapping=mapping,measurement_acceptance_pass=unchanged and all(p['measurement_acceptance_pass'] for p in reports.values()),
            quantitative_field_attribution_ready=False,requires_actual_load_calibration=True,
            scope='Offline recheck only; original ETL, exports, counters and previous quality reports preserved')
        (output/'acceptance.json').write_text(json.dumps(acceptance,indent=2)+'\n')
        print(case.name,acceptance['measurement_acceptance_pass'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('runs',type=Path);p.add_argument('--subdir',default='split_rechecked03');main(p.parse_args())
