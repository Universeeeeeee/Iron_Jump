"""Offline nested model-call bounds from already retained records; no exclusive attribution."""
import hashlib,json,statistics
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def join(work):
    adapters=work['rows']['adapter_calls'];inferences=work['rows']['inferences']
    lookup={v['timestamp_ms']:v for v in adapters}
    assert len(lookup)==len(adapters)==len(inferences) and len({v['adapter'] for v in adapters})==1
    rows=[];used=set()
    for inference in inferences:
        r=inference['record'];value=r['frame_timestamp_s']*1000;key=round(value)
        assert abs(value-key)<1e-5 and key not in used;used.add(key);a=lookup[key]
        start,end=round(r['inference_start_s']*1e9),round(r['inference_end_s']*1e9)
        assert a['tid']==inference['tid'] and start<=a['begin_ns']<=a['end_ns']<=end
        assert a['shape']==[360,640,3] and a['dtype']=='uint8' and a['error'] is None and r['error'] is None
        whole=end-start;base=a['end_ns']-a['begin_ns']
        rows.append(dict(frame_index=r['metadata']['frame_index'],timestamp_ms=key,whole_ms=whole/1e6,base_adapter_ms=base/1e6,outer_shell_ms=(whole-base)/1e6,has_pose=r['has_pose']))
    assert used==set(lookup)
    return rows
if __name__=='__main__':
    plan=read(HERE/'boundary_plan01.json');assert all(sha(ROOT/n)==v for n,v in plan['bindings'].items())
    archive=HERE/'runs/evidence01';manifest=read(archive/'manifest01.json');assert all(sha(archive/n)==v for n,v in manifest.items())
    result={}
    for case in read(HERE/'plan02.json')['cases']:
        work=read(archive/'runs/cohort01'/case['id']/'capture/workload_final.json');rows=join(work)
        result[case['id']]=dict(backend=case['backend'],calls=len(rows),all_calls_nested_and_same_native_thread=True,input_shape=[360,640,3],input_dtype='uint8',pose_present=sum(bool(r['has_pose']) for r in rows),
            wall_ms_medians={name:statistics.median(r[name] for r in rows) for name in ('whole_ms','base_adapter_ms','outer_shell_ms')})
    output=dict(scope='Posthoc nested-call wall intervals from the existing12-window archive only.',cases=result,
        code_boundaries=dict(base_adapter='vision/mediapipe_pose.py::MediaPipePoseAdapter.infer_bgr (RGB array, MediaPipe Image, detect_for_video, landmarks conversion)',outer_shell='vision/live_walking.py::_PreviewAdapter.infer_bgr plus call dispatch and retained audit event overhead outside the base markers'),
        limits=['Neither interval is pureCPU time; both can include GIL reacquisition, scheduling, native work and waits.','Outer shell is not equivalent to cv2.resize; audit event publication and Python return are included.','All frames have poses and fixed dimensions, but internal MediaPipe tracking/detection work and dynamic prior frame histories are not proven identical.','No function orGIL contribution percentage, kernel identification orperformance qualification follows.'],new_capture=False,primary_root_identified=False,bindings=plan['bindings'])
    with (HERE/'adapter_boundary01.json').open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps({n:v for n,v in result.items() if n.startswith('aa')},indent=2))
