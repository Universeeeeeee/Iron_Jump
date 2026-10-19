"""Only OpenCV parallelism changes; resize hashing is a common semantic gate."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    case=sys.argv[1];plan=json.loads((HERE/'plan01.json').read_text());assert case in plan['delivery_cases']
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'experiments/fixed_work_accounting'))
    sys.path.insert(0,str(ROOT/'experiments/native_stack_symbol_preflight'));from pe_identity import pe
    import cv2
    binary=Path(cv2.__file__).parent/'cv2.pyd';image=pe(binary);assert image['sha256']==plan['cv2_sha256']
    info=dict(pid=os.getpid(),case=case,errors=[],resized=[],cv2_image={k:image[k] for k in ('path','sha256','image_size','checksum')},configured_before=cv2.getNumThreads())
    assert info['configured_before']==plan['original_threads']
    if case=='one':cv2.setNumThreads(1)
    info['configured_after']=cv2.getNumThreads();assert info['configured_after']==(1 if case=='one' else plan['original_threads'])
    original=cv2.resize
    def observed_resize(*args,**kwargs):
        out=original(*args,**kwargs)
        info['resize_tid']=threading.get_native_id()
        info['resized'].append(dict(ordinal=len(info['resized']),shape=list(out.shape),dtype=str(out.dtype),sha256=hashlib.sha256(out.tobytes()).hexdigest()))
        return out
    cv2.resize=observed_resize
    spec=importlib.util.spec_from_file_location('fixed_concurrent_original',ROOT/'experiments/fixed_overlap_comparison/workload.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner);runner.HERE=HERE/'child'
    child=json.loads((runner.HERE/'plan01.json').read_text());assert child['cases']==plan['delivery_cases'] and all(v=='concurrent' for v in child['case_variants'].values())
    code=1
    try:
        code=runner.child(case);info['workload_returncode']=code
        assert len(info['resized'])==child['model_calls'] and all(x['shape']==[360,640,3] and x['dtype']=='uint8' for x in info['resized'])
        info['sources_unchanged']=all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
        info['cv2_binary_unchanged']=sha(binary)==plan['cv2_sha256']
    except BaseException as exc:info['errors'].append(repr(exc));code=1
    finally:
        cv2.resize=original;info['resize_wrapper_restored']=True
        with (HERE/(case+'_meta.json')).open('x') as f:json.dump(info,f,indent=2)
    print(json.dumps(dict(case=case,returncode=code,errors=info['errors'])));raise SystemExit(code)
