"""Same-process source/decode/model reference for the exact retained dynamic schedule."""
import json
from pathlib import Path
import sys

from common import Media,canonical_pose,preview_identity,sha

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

if __name__=='__main__':
    plan=json.loads((HERE/'plan04.json').read_text());output=Path(sys.argv[1]);assert not output.exists()
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert sha(Path(plan['model_path']))==plan['model_sha256']
    sys.path.insert(0,str(ROOT));from vision.live_walking import _PreviewAdapter
    schedule=json.loads((HERE/'selection01.json').read_text());by_frame={}
    for call in schedule['inferences']:by_frame.setdefault(call['frame_index'],[]).append(call)
    adapter=_PreviewAdapter(Path(plan['model_path']));previews=[];inferences=[];errors=[]
    try:
        adapter.open()
        with Media(plan['input_root'],plan['media_sha256']) as media:
            for ordinal,frame_id in enumerate(schedule['preview_frame_ids']):
                frame,meta=media.decode(frame_id);previews.append(preview_identity(frame,meta,ordinal))
                for call in by_frame.get(frame_id,[]):
                    pose=adapter.infer_bgr(frame,call['timestamp_ms'])
                    inferences.append(dict(**call,pose_sha256=canonical_pose(pose)))
    except BaseException as exc:errors.append(repr(exc))
    finally:
        try:adapter.close()
        except BaseException as exc:errors.append(repr(exc))
    result=dict(complete=not errors,errors=errors,pid=__import__('os').getpid(),previews=previews,inferences=inferences,
        model_closed=not adapter.is_open,scope='Same-process saved media decode plus original PreviewAdapter. NoGUI,SDK,device orperformance claim.')
    with output.open('x') as f:json.dump(result,f,indent=2)
    assert result['complete'] and len(previews)==schedule['counts']['preview_frames'] and len(inferences)==schedule['counts']['inferences'] and result['model_closed']
