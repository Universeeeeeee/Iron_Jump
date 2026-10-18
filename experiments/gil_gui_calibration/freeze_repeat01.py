from pathlib import Path
import json,hashlib
r=Path(__file__).resolve().parents[2];d=Path(__file__).resolve().parent;h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'));p=read(d/'repeat_plan01.json')
old=read(d/'aa_frozen_sources01.json')['files'];assert all(h(r/n)==s for n,s in old.items())
assert h(d/'aa_plan01.json')==p['prior_capture_plan_sha256'] and h(d/'runs/off_aa01/result01.json')==p['prior_capture_result_sha256']
assert h(d/'evidence01.zip')==p['prior_archive_sha256']
assert all(h(r/n)==s for n,s in p['repeat_sources'].items())
assert all(h(Path(p['input_root'])/n)==s for n,s in p['input_sha256'].items())
assert all(h(r/n)==s for n,s in p['baseline_files'].items()) and all(h(r/n)==s for n,s in p['dependencies'].items())
files=dict(old);files.update(p['repeat_sources']);files['experiments/gil_gui_calibration/repeat_plan01.json']=h(d/'repeat_plan01.json');files['experiments/gil_gui_calibration/freeze_repeat01.py']=h(Path(__file__))
with (d/'repeat_frozen01.json').open('x') as f:json.dump({'files':files},f,indent=2)
print('Repeat frozen; original code/data/result/archive unchanged',len(files))
