from pathlib import Path
import json,numpy as np,hashlib
r=Path('E:/OptoJump/preview_delay_review_20261022');inv=json.loads((r/'inventory.json').read_text(encoding='utf-8'));rows=[]
for item in inv['runs']:
 p=Path(item['path']);report=json.loads((p/'actor/report.json').read_text(encoding='utf-8'));events=report['walking_summary']['event_publications'];origin=min(e['touch_sample'] for e in events)/1000
 with np.load(p/'actor/exports.npz',allow_pickle=False) as z:t=z['timestamps']
 first=round((float(t[0])+origin)*1000);last=round((float(t[-1])+origin)*1000);touches=[e['touch_sample'] for e in events];rows.append(dict(run=p.name,source_report_sha256=hashlib.sha256((p/'actor/report.json').read_bytes()).hexdigest(),retained_frames=len(t),first_sample=first,last_sample=last,first_touch=min(touches),last_touch=max(touches),all_landings_retained=first<=min(touches) and last>=max(touches),consecutive_1ms_samples=bool(np.allclose(np.diff(t),.001,rtol=0,atol=1e-8))))
(r/'raw_retention.json').write_text(json.dumps(rows,indent=2),encoding='utf-8');print(json.dumps(rows))
