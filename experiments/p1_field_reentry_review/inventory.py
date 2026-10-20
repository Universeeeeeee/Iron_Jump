"""Inventory retained field JSON without redefining old acceptance thresholds."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))

if __name__=='__main__':
    root=HERE/'runs';rows=[]
    for case in sorted(p for p in root.iterdir() if p.is_dir()):
        files={p.name:sha(p) for p in case.iterdir() if p.is_file()}
        data={p.stem:read(p) for p in case.iterdir() if p.is_file() and p.suffix=='.json'}
        rows.append(dict(case=case.name,files=files,json_top_level_keys={k:sorted(v) for k,v in data.items()}))
    out=dict(cases=rows,source_files_read_only=True,device_or_workload_started=False)
    with (HERE/'inventory01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
