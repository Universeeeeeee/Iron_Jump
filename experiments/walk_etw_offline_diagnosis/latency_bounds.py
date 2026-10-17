"""Offline bounds from existing consumer-completion witnesses and GUI receipts.

Only consumer-thread queue_common points bound publication: a separate observer
can see an incomplete batch after that batch already published a contact.
"""
import argparse
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
NAMES = ['20261017_111818_dc83b931_walk_off', '20261017_112623_8416401b_walk_on',
         '20261017_113358_00ae9eca_walk_on', '20261017_113916_32a7af0d_walk_off']


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def analyze(name):
    p = HERE.parent / 'single_usb_human_etw/runs' / name / 'capture'
    m, report, visual = read(p / 'measurement.json'), read(p / 'report.json'), read(p / 'visual_events.json')
    with np.load(p / 'raw_frames.npz') as raw:
        receipts = dict(zip(map(int, raw['sample_indices']), map(int, raw['received_ns'])))
    common = sorted(m['queue_common'], key=lambda r: r[0])
    first_visual = {}
    for event in visual:
        for foot in event['frame']['feet']:
            if foot.get('status') == 'confirmed':
                first_visual.setdefault(foot['contact_id'], event['host_ns'])
    events = []
    for event in report['walking_summary']['event_publications']:
        if not event['active']:
            continue
        touch, published, cid = event['touch_sample'], event['published_sample'], event['contact_id']
        index = next(i for i, row in enumerate(common) if row[1] >= published)
        assert index > 0
        lower, upper = common[index - 1][0], common[index][0]
        v, paint = first_visual[cid], m['paints'][str(cid)]
        assert v >= lower and paint >= v, 'Publication/GUI/paint order disagrees'
        events.append({'contact_id': cid, 'touch_sample': touch, 'published_sample': published,
                       'confirmation_device_samples': published - touch,
                       'touch_receipt_to_paint_ms': (paint - receipts[touch]) / 1e6,
                       'publication_consumer_host_bracket_formal_s': [(lower - m['armed_ns']) / 1e9, (upper - m['armed_ns']) / 1e9],
                       'consumer_publication_bracket_width_ms': (upper - lower) / 1e6,
                       'published_sample_receipt_to_publication_bounds_ms': [max(0, lower - receipts[published]) / 1e6, max(0, upper - receipts[published]) / 1e6],
                       'publication_to_GUI_receipt_bounds_ms': [max(0, v - upper) / 1e6, max(0, v - lower) / 1e6],
                       'GUI_first_confirmed_receipt_to_paint_ms': (paint - v) / 1e6})
    return {'case': name, 'events': events,
            'largest_GUI_receipt_to_paint_ms': max(e['GUI_first_confirmed_receipt_to_paint_ms'] for e in events),
            'largest_GUI_delivery_upper_bound_ms': max(e['publication_to_GUI_receipt_bounds_ms'][1] for e in events),
            'last_event': events[-1]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert not args.output.exists()
    result = {'trials': [analyze(name) for name in NAMES],
              'scope': 'Post-hoc interval attribution only. No acceptance metric or original report is changed. Published sample is a device index, not a measured host publication timestamp.',
              'limits': ['Batch witnesses bound publication; they do not measure exclusive stage time.',
                         'GUI visual signal receipt and first paint are program timestamps, not physical display exposure.',
                         'Unpublished physical steps are excluded; total agreement is not per-step correctness.']}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    for trial in result['trials']:
        print(trial['case'], trial['largest_GUI_delivery_upper_bound_ms'], trial['largest_GUI_receipt_to_paint_ms'], trial['last_event'])
