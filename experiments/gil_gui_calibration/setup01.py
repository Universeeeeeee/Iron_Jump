from pathlib import Path
import json,hashlib,shutil
r=Path(__file__).resolve().parents[2];formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017');prior=Path('E:/OptoJump/IronJump-ground-backlog-measurement-20261016');here=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'));h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
base=read(formal/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files'];deps=read(formal/'experiments/single_usb_human_etw/dependencies.json')['files']
assert all(h(formal/n)==v for n,v in base.items()) and all(h(formal/n)==v for n,v in deps.items())
for n,v in {**base,**deps}.items():
 out=r/n;out.parent.mkdir(parents=True,exist_ok=True);assert not out.exists();shutil.copy2(formal/n,out);assert h(out)==v
out=r/'experiments/runtime_single_frame_fusion/baseline_manifest.json';shutil.copy2(formal/'experiments/runtime_single_frame_fusion/baseline_manifest.json',out)
for n in ('enabled_replay.py',):
 dest=r/'experiments/ground_throughput_diagnosis'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(prior/'experiments/ground_throughput_diagnosis'/n,dest)
shutil.copy2(prior/'experiments/ground_backlog_measurement/phases.json',here/'phases.json')
inputs=prior/'experiments/ground_backlog_measurement/inputs/walk';oracle=prior/'experiments/ground_backlog_measurement/oracles/walk'
# Input/oracle source directories remain read-only references. No media copied to Git.
plan=dict(scope='One functional smoke only of fixed saved Walk input/video plus original enabled GUI/pose and real SDK. No observer, physical USB or native camera capture, human Walk, Run or optimization. No disturbance success claim.',input_root=str(inputs),oracle_root=str(oracle),sources={p.relative_to(r).as_posix():h(p) for p in here.glob('*') if p.is_file() and p.suffix in ('.py','.json')},input_sha256={p.relative_to(inputs).as_posix():h(p) for p in inputs.rglob('*') if p.is_file()},oracle_sha256={p.relative_to(oracle).as_posix():h(p) for p in oracle.rglob('*') if p.is_file()},baseline_sha256=h(out),baseline_files=base,dependencies=deps,numpy_pyd_sha256=h(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd')),helper_sha256=h(r/'experiments/ground_throughput_diagnosis/enabled_replay.py'),actual_load_disturbance_pass=False,field_attribution_ready=False)
with (here/'smoke_plan01.json').open('x') as f:json.dump(plan,f,indent=2)
print(json.dumps(dict(files=len(base),dependencies=len(deps),input_files=len(plan['input_sha256']),input_bytes=sum(p.stat().st_size for p in inputs.rglob('*') if p.is_file()),formal_frames=read(inputs/'report.json')['report_config_snapshot']['raw_buffer']['total_received_frames'],plan_sha256=h(here/'smoke_plan01.json'))))
