"""Verify the state-only counterfactual and the actual delivered video pixels."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image
from analyze import metrics

HERE = Path(__file__).resolve().parent


if __name__ == '__main__':
    results = []
    for folder in sorted((HERE / 'runs').glob('preview_*')):
        result = metrics(folder)
        state = json.loads((folder / 'state_marker.json').read_text())
        delivery = json.loads((folder / 'external_delivery.json').read_text())
        assert delivery['source_sha256'] == hashlib.sha256((HERE / 'state_target.py').read_bytes()).hexdigest()
        assert delivery['system_exit_code'] == 0
        enabled = state['preview_state'] == 'enabled'
        assert delivery['draws'] and all(bool(row[-1]) == enabled for row in delivery['draws'])
        image = np.asarray(Image.open(folder / 'live_overlay.png').convert('RGB'))
        assert image.shape[:2] == (1055, 1813), 'Record and review a new ROI if desktop geometry changes'
        # Fixed, stated image-only screen ROI; excludes banner, labels and track.
        region = image[350:900, 50:1000].astype(np.int16)
        fraction = float(np.mean(np.ptp(region, axis=2) > 5))
        result.update(preview_state=state['preview_state'], actual_canvas_enabled=enabled,
                      delivered_video_roi=[50, 350, 1000, 900],
                      delivered_video_fraction_chroma_above_5=fraction,
                      process_cleanup=state,
                      scope='E/O/E diagnostic pilot only; not a successful new M/D calibration or optimization adoption')
        results.append(result)
    assert len(results) == 6
    output = {'runs': results, 'factor': 'offline preview QWidget enabled state',
              'all_raw_reports_quality_runtime_events_exact': True,
              'new_stage_calibration_completed': False,
              'all_rounds_retained': True}
    (HERE / 'preview_state_summary.json').write_text(json.dumps(output, indent=2) + '\n')
    rows = [{'run': r['name'], 'mode': r['mode'], 'state': r['preview_state'],
             'canvas_enabled': r['actual_canvas_enabled'],
             'video_chroma_fraction': r['delivered_video_fraction_chroma_above_5'],
             'dense_fps': r['phases']['dense']['consumer_fps'],
             'dense_age_slope_ms_per_device_s': r['phases']['dense']['age_slope_ms_per_device_second'],
             'footprint_p95_ms': r['receipt_to_paint_ms']['p95'],
             'footprint_max_ms': r['receipt_to_paint_ms']['max']} for r in results]
    with (HERE / 'preview_state_runs.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(rows, indent=2))
