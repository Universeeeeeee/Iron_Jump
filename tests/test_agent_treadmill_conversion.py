import pytest

from agent.config.models import LLMTreadmillGaitConfig, LLMTreadmillRunningConfig


@pytest.mark.parametrize('model', [LLMTreadmillGaitConfig, LLMTreadmillRunningConfig])
@pytest.mark.parametrize('stop_type,length', [('Software command', None), ('End of Time', '00:30')])
def test_treadmill_agent_preserves_required_nullable_duration(model, stop_type, length):
    result = model(stop_type=stop_type, test_length=length).to_test_config()
    assert result.stop_type == stop_type
    assert result.test_length == length
