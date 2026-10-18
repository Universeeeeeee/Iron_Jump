"""Preserve the explicitly requested repeat separately from the earlier cohort."""
import hashlib
import json
from pathlib import Path
import zipfile


here=Path(__file__).resolve().parent;root=here.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
stage=here/'runs/restart_repeat01';assert (stage/'result01.json').is_file()
assert read(here/'post_repeat01.json')['preservation_pass'],'No archive until quiescence confirmed'
status=read(stage/'result01.json');names=set(read(here/'repeat_frozen01.json')['files'])
names.update(p.relative_to(root).as_posix() for p in stage.rglob('*') if p.is_file())
names.update('experiments/gil_gui_calibration/'+n for n in ('repeat_frozen01.json','post_repeat01.py','post_repeat01.json','collect_repeat01.py','repeat_preflight01.json','repeat_launch_record01.json','repeat_analysis_plan01.json','review_repeat01.py','review_aa01.py','review_progress01.py','repeat_task01.log'))
manifest={n:sha(root/n) for n in sorted(names)}
with (here/'repeat_manifest01.json').open('x') as f:json.dump(manifest,f,indent=2)
with zipfile.ZipFile(here/'evidence_restart_repeat01.zip','x',zipfile.ZIP_DEFLATED) as z:
    for n in manifest:z.write(root/n,n)
    z.write(here/'repeat_manifest01.json','manifest.json');z.write(stage/'active.lock',stage.relative_to(root).as_posix()+'/active.lock/')
print(json.dumps(dict(archive_sha256=sha(here/'evidence_restart_repeat01.zip'),manifest_files=len(manifest),fixed_cases_completed=len(status['cases']),errors=status['errors'])))
