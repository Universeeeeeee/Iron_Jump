import pytest

from tools.validate_walking_pairing import CASES, run_case


@pytest.mark.parametrize('case', CASES)
def test_pairing_fault_matrix(case):
    result = run_case(case)
    assert result['passed'], result
    assert result['final_check']['device_side'] == 'right'
    for event in result['events']:
        assert event['event_time_s'] == pytest.approx(102.0)
        for frame in event['frame_window']:
            assert abs(frame['aligned_time_s'] - event['event_time_s']) <= .150001
            assert frame['aligned_time_s'] - frame['sample_time_s'] == pytest.approx(100.0)
            source = frame['metadata']
            assert source['sample_time_s'] == frame['sample_time_s']
            assert source['callback_time_s'] >= 100 + source['sample_time_s']
    if case in {'left', 'right', 'one_frame_dropped'}:
        assert result['events']
        decision = result['events'][0]['decision']
        assert decision['diagnostics']['pose_before'] >= 2
        assert decision['diagnostics']['pose_after'] >= 2
        assert decision['decided_at_s'] <= 102.450
    if case == 'excluded_decided':
        assert any(t['check']['label'] == 'left' for t in result['display_transitions'] if t['check'])
        assert result['final_check']['reason'] == 'contact_unavailable'
    if case == 'two_frames_dropped':
        assert result['final_check']['reason'] == 'pose_gap_exceeded'
    if case == 'slow_inference':
        assert result['final_check']['reason'] == 'decision_timeout'
