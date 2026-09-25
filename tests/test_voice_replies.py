from voice.replies import concise_reply


def test_short_control_and_config_feedback_stays_complete():
    text = "速度每小时3.6公里。测试10分钟。请说确认配置。"
    assert concise_reply(text) == text


def test_long_answer_keeps_complete_metrics_and_limits_spoken_detail():
    first = "步频均值120.000步/分钟，有效样本20条。"
    text = first + "完整周期不足，暂不能评价。" + "更多分析内容。" * 30
    result = concise_reply(text)
    assert result == first + "完整周期不足，暂不能评价。其余详情见页面。"
    assert text.endswith("更多分析内容。" * 30)
