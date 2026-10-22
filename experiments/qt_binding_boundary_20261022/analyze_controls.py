"""Verify each intervention's delivery count and role against original traces."""
import json
from pathlib import Path
import subprocess
import sys

here = Path(__file__).resolve().parent
folder = Path(sys.argv[1])
subprocess.run([sys.executable, str(here / 'analyze_binding.py'), str(folder)], check=True)
result = json.loads((folder / 'analysis.json').read_text())
for case in result['cases']:
    target = folder / case['case']
    files = list(target.glob('quality_dispatch_*.json')) + list(target.glob('source_dispatch_*.json'))
    records = [json.loads(p.read_text()) for p in files]
    active = [record for record in records if record['deliveries']]
    assert len(records) == 2 and len(active) == 1
    control = active[0]
    assert control['mode'] == case['case'].split('_')[-1]
    assert len(control['deliveries']) == 1
    delivery = control['deliveries'][0]
    assert delivery['count'] > 11000
    rows = json.loads((target / f"trace_{control['pid']}.json").read_text())['rows']
    source = next(row for row in rows if row['stage'] == 'source_start')
    consumer = next(row for row in rows if row['stage'] == 'consumer_complete')
    if any(p.name.startswith('source_dispatch_') for p in files):
        assert delivery['tid'] == source['tid'] != consumer['tid']
        assert delivery['count'] == case['wire'][0]['verified_frames']
        control['boundary'] = 'reader_to_inbox'
    else:
        assert delivery['tid'] == consumer['tid'] != source['tid']
        control['boundary'] = 'quality_to_engine'
    case['dispatch_control'] = control
result['limits'].append('Direct callback controls validate normal-path delivery only; production exception, disconnect and lifecycle behavior is not certified. No production deployment or latency percentage claim follows.')
(folder / 'analysis.json').write_text(json.dumps(result, indent=2) + '\n')
