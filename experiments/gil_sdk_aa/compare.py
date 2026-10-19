"""Necessary pair workload identity; unequal inputs cannot qualify overhead."""
def identities(measurement,review):
    w=review['legacy_workload']
    return dict(video=measurement['video_indices'],whole_inference=w['whole_inference_frame_ids'],ROI_inference=w['ROI_inference_identities'],
                service_submits=w['service_submit_call_count'],SDK_pose_inputs=w['SDK_pose_input_count'],SDK_calls=w['SDK_call_count'],
                tracking_decisions=measurement['sdk']['tracking_decisions'],nonzero_speeds=measurement['sdk']['nonzero_speeds'],valid_draws=measurement['pose_draws']['valid'])

def compare(a,b):
    checks={k:a[k]==b[k] for k in a}
    return dict(checks=checks,necessary_workload_identity_pass=all(checks.values()),
                independent_pairs=1,variance_estimate_available=False,actual_load_disturbance_pass=False,field_attribution_ready=False,
                reason='One prospective pair is a comparability check, not a variance estimate. All common observers remain enabled; their absolute cost is unqualified.')
