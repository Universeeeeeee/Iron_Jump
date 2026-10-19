"""Partial-stop ingress/archive accounting only; not full partial-report oracle."""
import hashlib
import json
import sys

def verify_partial_stop(folder,root,checked):
    import numpy as np
    sys.path.insert(0,str(root/'experiments/gil_gui_calibration'));from semantics02 import source,read
    actor=read(folder/'result.json');report=read(folder/'report.json');state=read(folder/'state.json');expected=source('walk')['data']
    accepted=actor['accepted_last_sample']
    assert checked<accepted<int(expected['sample_indices'][-1])
    with np.load(folder/'raw_frames.npz') as raw:
        length=len(raw['sample_indices'])
        for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):
            assert np.array_equal(raw[key],expected[key][:length]),key
        assert np.all(np.diff(raw['received_ns'])>=0)
        mask=(raw['sample_indices']>checked)&(raw['sample_indices']<=accepted)
        assert int(np.count_nonzero(mask))==accepted-checked
        assert hashlib.sha256(raw['bits'][mask].tobytes()).hexdigest()==state['raw_archive_sha256']
    assert report['finish_reason']=='manual'
    assert report['report_config_snapshot']['raw_buffer']['total_received_frames']==accepted-checked
    return dict(partial_ingress_prefix_exact=True,accepted_raw_archive_exact=True,accepted_last_sample=accepted,accepted_formal_frames=accepted-checked,
                all_ingress_frames=length,post_freeze_ingress_frames=actor['source_count']-(accepted-int(expected['sample_indices'][0])+1),
                partial_report_algorithm_oracle=False,performance_qualification=False)
