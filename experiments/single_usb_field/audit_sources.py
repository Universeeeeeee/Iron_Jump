"""Offline hash audit against frozen runtime and previously archived evidence."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    base=read(ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    mismatch=[n for n,h in base.items() if sha(ROOT/n)!=h];assert not mismatch,mismatch
    frozen=[]
    for rel in ('single_usb_field','single_usb_native_calibration'):
        manifest=ROOT/'experiments'/rel/'frozen_sources.json'
        for n,h in read(manifest)['files'].items():assert sha(ROOT/n)==h,n
        frozen.append({'directory':rel,'manifest_sha256':sha(manifest),'files':len(read(manifest)['files'])})
    previous=[]
    old=ROOT/'experiments/ground_backlog_measurement';manifest=read(old/'final_evidence_manifest.json')
    for section in ('local_metadata','logs'):
        for name,info in manifest[section].items():assert sha(old/name)==info['sha256'],name;previous.append(str((old/name).relative_to(ROOT)))
    empty=ROOT/'experiments/single_usb_empty'
    for name,info in read(empty/'evidence_manifest.json')['files'].items():assert sha(empty/name)==info['sha256'],name
    result={'baseline_original_files_checked':len(base),'baseline_mismatch':mismatch,'frozen_runtime':frozen,'prior_backlog_evidence_files_checked':len(previous),'prior_empty_evidence_files_checked':len(read(empty/'evidence_manifest.json')['files']),'previous_evidence_mismatch':[],'candidate_changed':False,'scope':'Read-only local worktree and retained evidence audit; Windows original source hashes audited separately.'}
    (HERE/'local_source_audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
