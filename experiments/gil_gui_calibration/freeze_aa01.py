from pathlib import Path
import json,hashlib
r=Path(__file__).resolve().parents[2];d=Path(__file__).resolve().parent;h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'));p=read(d/'aa_plan01.json')
assert all(h(r/n)==s for n,s in p['sources'].items())
assert all(h(Path(p['input_root'])/n)==s for n,s in p['input_sha256'].items())
assert all(h(r/n)==s for n,s in p['baseline_files'].items()) and all(h(r/n)==s for n,s in p['dependencies'].items())
files=dict(p['sources']);files['experiments/gil_gui_calibration/aa_plan01.json']=h(d/'aa_plan01.json');files['experiments/gil_gui_calibration/freeze_aa01.py']=h(Path(__file__))
with (d/'aa_frozen_sources01.json').open('x') as f:json.dump({'files':files},f,indent=2)
print('AA independently frozen',len(files))
