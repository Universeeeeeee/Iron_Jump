"""Display names; persisted mode identifiers remain stable."""

MODE_LABELS = {
    "Jump Test": "纵跳测试",
    "Treadmill Gait Test": "跑步机走路",
    "Treadmill Running Test": "跑步机跑步",
    "Sprint and Gait Test": "地面走路",
    "Overground Running Test": "地面跑步",
    "Tapping Test": "踏步测试",
    "Reaction Times": "反应时测试",
    "Static Test (Sway)": "静态平衡测试",
}


def mode_label(test_type: str) -> str:
    return MODE_LABELS.get(test_type, test_type)
