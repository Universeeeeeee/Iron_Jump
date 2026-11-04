"""A fixed onset coordinate, independent of the later confirmation threshold."""

def first_contact_reference(positions, touch_sample, observations, bad_indices=()):
    result = dict(valid=False, value=None, sample=touch_sample,
                  basis='first_observed_contact_center_v1', missing_reason='onset_position_not_observed')
    for sample, low, high, unknown in observations:
        if sample != touch_sample:
            continue
        if unknown or low == 0 or high == len(positions)-1 or any(low <= i <= high for i in bad_indices):
            result['missing_reason'] = 'onset_position_uncertain'
            return result
        result.update(valid=True, value=(positions[low]+positions[high])/2, missing_reason=None)
        return result
    return result
