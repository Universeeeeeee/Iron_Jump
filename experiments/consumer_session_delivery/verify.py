"""Compare full original report, state and raw delivery; no GUI efficacy checks."""
import copy
import json
import sys

def verify_values(folder,root):
    import numpy as np
    sys.path.insert(0,str(root/'experiments/gil_gui_calibration'))
    from semantics02 import source,canonical,read,HERE
    expected=source('walk');data=expected['data']
    with np.load(folder/'raw_frames.npz') as delivered:
        for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):
            if not np.array_equal(delivered[key],data[key]):raise ValueError('Raw field changed: '+key)
        received=delivered['received_ns'];assert np.all(np.diff(received)>=0);checked=int(received[3500])
    report=read(folder/'report.json');assert canonical(copy.deepcopy(report),checked)==read(HERE/'oracles/walk/report.json')
    state=read(folder/'state.json');assert state['quality']['preflight']['checked_monotonic_ns']==checked
    del state['quality']['preflight']['checked_monotonic_ns']
    assert state==read(HERE/'oracles/walk/state.json')
    return dict(full_original_report=True,full_quality_runtime_state=True,raw_fields_exact=True,source_frames=len(received),checked_sample=expected['checked'],performance_qualification=False)
