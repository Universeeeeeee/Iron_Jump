from pathlib import Path
import json,hashlib
r=Path(__file__).resolve().parents[2];d=Path(__file__).resolve().parent;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'));p=read(d/'smoke_plan01.json')
assert all(sha(r/n)==h for n,h in p['sources'].items()) and all(sha(r/n)==h for n,h in p['baseline_files'].items())
paths=[x for x in d.iterdir() if x.is_file()];paths.extend([r/'experiments/ground_throughput_diagnosis/enabled_replay.py',r/'experiments/runtime_single_frame_fusion/baseline_manifest.json'])
with (d/'frozen_sources.json').open('x') as f:json.dump({'files':{x.relative_to(r).as_posix():sha(x) for x in paths}},f,indent=2)
print('Sources frozen',len(paths))
