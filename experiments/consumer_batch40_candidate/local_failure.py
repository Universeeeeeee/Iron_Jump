"""Retain failed original-baseline raw prefixes and reports without claiming cleanup."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments/session_local_baseline'))
from local import LocalSession

def preserve(client):
    import numpy as np
    folder=client.folder/'failed_capture';folder.mkdir(exist_ok=False)
    source=client.source;frames=tuple(getattr(source,'delivered',()))
    reader=getattr(source,'reader',None);alive=reader is not None and reader.is_alive()
    if frames:
        np.savez_compressed(folder/'raw_prefix.npz',**{k:np.array([getattr(f,a) for f in frames]) for k,a in [('sample_indices','sample_index'),('frame_indices','frame_index'),('received_ns','received_monotonic_ns'),('dropped_frames_before','dropped_frames_before')]},bits=np.array([np.frombuffer(f.contact_bits,np.uint8) for f in frames]),valid_bits=np.array([np.frombuffer(f.valid_bits,np.uint8) for f in frames]),wire=np.array([np.frombuffer(f.wire_payload,np.uint8) for f in frames]))
    with (folder/'reports.json').open('x',encoding='utf-8') as f:json.dump(client.reports,f,ensure_ascii=False,indent=2)
    with (folder/'metadata.json').open('x') as f:json.dump(dict(frame_count=len(frames),reader_alive=alive,prefix_only=alive,cleanup_confirmed=False,
        reports=len(client.reports),frame_metadata=[dict(sample=f.sample_index,stream_id=f.stream_id,quality_flags=f.quality_flags) for f in frames]),f,indent=2)

class RetainingLocal(LocalSession):
    def _fail(self,error):
        if self.finished:return
        try:super()._fail(error)
        finally:
            if self.folder.exists():preserve(self)
