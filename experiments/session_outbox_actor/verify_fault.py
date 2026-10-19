"""Validate accepted raw evidence after deliberately failed actor transport."""
import hashlib
import sys

def verify_fault_values(folder,root,checked):
    import numpy as np
    sys.path.insert(0,str(root/'experiments/gil_gui_calibration'));from semantics02 import source,read
    actor=read(folder/'result.json');report=read(folder/'report.json');state=read(folder/'state.json');expected=source('walk')['data']
    accepted=actor['accepted_last_sample'];assert checked<=accepted<int(expected['sample_indices'][-1])
    with np.load(folder/'raw_frames.npz') as raw:
        count=len(raw['sample_indices'])
        for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(raw[key],expected[key][:count]),key
        assert np.all(np.diff(raw['received_ns'])>=0)
        mask=(raw['sample_indices']>checked)&(raw['sample_indices']<=accepted)
        assert int(np.count_nonzero(mask))==accepted-checked==report['report_config_snapshot']['raw_buffer']['total_received_frames']
        assert hashlib.sha256(raw['bits'][mask].tobytes()).hexdigest()==state['raw_archive_sha256']
    snapshot=read(folder/'output_snapshot/state.json')
    assert snapshot['state']['failure'] is not None
    for name,digest in snapshot['unconfirmed_files'].items():assert hashlib.sha256((folder/'output_snapshot'/name).read_bytes()).hexdigest()==digest
    return dict(actual_ingress_prefix_frames=count,accepted_formal_frames=accepted-checked,raw_prefix_and_accepted_archive_exact=True,
                partial_report_locally_saved=True,unconfirmed_packet_hashes_pass=True,partial_report_algorithm_oracle=False,
                performance_qualification=False)
